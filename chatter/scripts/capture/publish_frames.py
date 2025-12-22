#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional, Tuple

import redis
from jsonschema import Draft202012Validator, FormatChecker

try:  # Optional for local dev
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency managed via pyproject
    load_dotenv = None

try:  # Optional for file conversion / non-png dimensions
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency
    Image = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv_if_present() -> None:
    if load_dotenv is None:
        return
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


_load_dotenv_if_present()


def _opt_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _resolve_redis_url(cli_value: Optional[str]) -> str:
    """
    Resolve Redis URL for host-run scripts.

    Precedence:
      1) CLI --redis-url
      2) REDIS_URL_HOST (recommended for host)
      3) REDIS_URL (often docker-internal: redis://redis:6379/0)
      4) fallback localhost
    """
    return (
        (cli_value or "").strip()
        or _opt_env("REDIS_URL_HOST")
        or _opt_env("REDIS_URL")
        or "redis://127.0.0.1:6379/0"
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_room_id_for_path(room_id: str) -> str:
    raw = (room_id or "").strip()
    if not raw:
        return "room_unknown"
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    return "".join(ch if ch in allowed else "_" for ch in raw)


def _png_dimensions(path: Path) -> Tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    if header[12:16] != b"IHDR":
        raise ValueError("missing IHDR chunk")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width < 1 or height < 1:
        raise ValueError("invalid PNG dimensions")
    return width, height


def _image_dimensions(path: Path) -> Tuple[int, int]:
    if Image is not None:
        with Image.open(path) as img:
            width, height = img.size
        if width < 1 or height < 1:
            raise ValueError("invalid image dimensions")
        return int(width), int(height)
    return _png_dimensions(path)


def _ensure_output_dir_within_repo(out_dir: Path) -> Tuple[Path, Path]:
    resolved = out_dir.resolve()
    repo = REPO_ROOT.resolve()
    try:
        rel = resolved.relative_to(repo)
    except ValueError as exc:
        raise ValueError(f"--out-dir must be within repo root ({repo}): {resolved}") from exc
    return resolved, rel


def _next_seq(room_dir: Path) -> int:
    if not room_dir.exists():
        return 1
    best = 0
    for path in room_dir.glob("frame_*.png"):
        stem = path.stem
        if not stem.startswith("frame_"):
            continue
        suffix = stem[len("frame_") :]
        try:
            num = int(suffix)
        except ValueError:
            continue
        best = max(best, num)
    return best + 1 if best >= 1 else 1


def _load_stream_frame_validator() -> Draft202012Validator:
    schema_path = REPO_ROOT / "packages" / "protocol" / "jsonschema" / "stream_frame.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


STREAM_FRAME_VALIDATOR = _load_stream_frame_validator()


def _validate_stream_frame(event: Dict[str, Any]) -> None:
    errors = sorted(STREAM_FRAME_VALIDATOR.iter_errors(event), key=lambda e: list(e.path))
    if not errors:
        return
    rendered = "; ".join([f"{'/'.join(map(str, err.path)) or '$'}: {err.message}" for err in errors[:5]])
    raise ValueError(f"StreamFrame schema invalid: {rendered}")


def _write_png_from_file(src: Path, dest: Path) -> str:
    if not src.exists():
        raise FileNotFoundError(f"input file missing: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    with src.open("rb") as handle:
        head = handle.read(8)
    if head != b"\x89PNG\r\n\x1a\n":
        if Image is None:
            raise RuntimeError("Non-PNG input; install Pillow for conversion: pip install pillow")
        with Image.open(src) as img:
            img.save(dest, format="PNG")
        return "png"

    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    return "png"


def _capture_screen_png(dest: Path) -> Tuple[int, int]:
    try:
        import mss  # type: ignore
        import mss.tools  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Missing mss; install with: pip install mss") from exc

    dest.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
        png_bytes = mss.tools.to_png(shot.rgb, shot.size)
        dest.write_bytes(png_bytes)
        width, height = shot.size
        return int(width), int(height)


def _connect_redis(redis_url: str) -> redis.Redis:
    client = redis.from_url(redis_url, decode_responses=True)
    client.ping()
    return client


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish StreamFrame events to Redis Streams (host-run)")
    parser.add_argument("--room-id", default="room:demo")
    parser.add_argument("--interval-ms", type=int, default=2000)
    parser.add_argument("--mode", choices=["screen", "file"], default="screen")
    parser.add_argument("--file", dest="file_path", default=None, help="Required when --mode file")
    parser.add_argument("--redis-url", default=None, help="Override Redis URL (else REDIS_URL_HOST/REDIS_URL)")
    parser.add_argument("--frames-key", default=None, help="Override STREAM_FRAMES_KEY")
    parser.add_argument("--out-dir", default="data/stream_frames")
    parser.add_argument("--source", default="host_capture")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    redis_url = _resolve_redis_url(args.redis_url)
    frames_key = args.frames_key or _opt_env("STREAM_FRAMES_KEY", "stream:frames")
    if not redis_url:
        print("FAIL: missing redis url; set REDIS_URL_HOST/REDIS_URL or pass --redis-url")
        return 2
    if not frames_key:
        print("FAIL: missing frames stream key; set STREAM_FRAMES_KEY or pass --frames-key")
        return 2

    if args.mode == "file" and not args.file_path:
        print("FAIL: --file is required when --mode file")
        return 2

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir_abs, _out_dir_rel = _ensure_output_dir_within_repo(out_dir)

    room_dir = out_dir_abs / _sanitize_room_id_for_path(args.room_id)
    seq = _next_seq(room_dir)

    try:
        client = _connect_redis(redis_url)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: Redis connection error ({redis_url}): {exc}")
        print("HINT: host scripts should usually use REDIS_URL_HOST=redis://127.0.0.1:6379/0")
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "mode": args.mode,
                "room_id": args.room_id,
                "out_dir": str(out_dir_abs),
                "stream": frames_key,
                "redis_url": redis_url,
                "interval_ms": int(args.interval_ms),
            },
            sort_keys=True,
        )
    )

    try:
        while True:
            wrote_path = room_dir / f"frame_{seq}.png"
            ts = _utc_now_iso()
            capture_ms = int(time.time() * 1000)

            try:
                if args.mode == "screen":
                    width, height = _capture_screen_png(wrote_path)
                    fmt = "png"
                else:
                    src = Path(args.file_path)
                    if not src.is_absolute():
                        src = (REPO_ROOT / src).resolve()
                    fmt = _write_png_from_file(src, wrote_path)
                    width, height = _image_dimensions(wrote_path)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL: capture/write error: {exc}")
                return 1

            sha256 = _sha256_file(wrote_path)

            # Publish as container-visible POSIX path.
            rel_path = wrote_path.resolve().relative_to(REPO_ROOT.resolve())
            frame_path = str(PurePosixPath("/app") / PurePosixPath(rel_path.as_posix()))

            frame_id = f"frame_{capture_ms}_{seq}"
            event: Dict[str, Any] = {
                "schema_name": "StreamFrame",
                "schema_version": "1.0.0",
                "id": frame_id,
                "ts": ts,
                "room_id": args.room_id,
                "frame_path": frame_path,
                "sha256": sha256,
                "width": int(width),
                "height": int(height),
                "format": fmt,
                "source": str(args.source),
                "seq": int(seq),
                "capture_ms": int(capture_ms),
            }

            try:
                _validate_stream_frame(event)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL: schema validation failed: {exc}")
                return 1

            try:
                redis_id = client.xadd(frames_key, {"data": json.dumps(event, ensure_ascii=False)})
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL: redis XADD failed: {exc}")
                return 2

            print(
                json.dumps(
                    {
                        "ok": True,
                        "schema_name": "StreamFrame",
                        "seq": int(seq),
                        "wrote": str(wrote_path),
                        "sha256": sha256,
                        "frame_path": frame_path,
                        "redis_stream": frames_key,
                        "redis_id": redis_id,
                    },
                    sort_keys=True,
                )
            )

            seq += 1
            time.sleep(max(args.interval_ms, 0) / 1000.0)
    except KeyboardInterrupt:
        print("Stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
