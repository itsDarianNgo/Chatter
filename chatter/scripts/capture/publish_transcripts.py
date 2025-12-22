#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import redis
from jsonschema import Draft202012Validator, FormatChecker

try:  # Optional for local dev
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency managed via pyproject
    load_dotenv = None


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


def _load_stream_transcript_validator() -> Draft202012Validator:
    schema_path = (
        REPO_ROOT / "packages" / "protocol" / "jsonschema" / "stream_transcript_segment.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


STREAM_TRANSCRIPT_VALIDATOR = _load_stream_transcript_validator()


def _validate_stream_transcript(event: Dict[str, Any]) -> None:
    errors = sorted(STREAM_TRANSCRIPT_VALIDATOR.iter_errors(event), key=lambda e: list(e.path))
    if not errors:
        return
    rendered = "; ".join([f"{'/'.join(map(str, err.path)) or '$'}: {err.message}" for err in errors[:5]])
    raise ValueError(f"StreamTranscriptSegment schema invalid: {rendered}")


def _connect_redis(redis_url: str) -> redis.Redis:
    client = redis.from_url(redis_url, decode_responses=True)
    client.ping()
    return client


def _iter_stdin_lines() -> Iterator[str]:
    for raw in sys.stdin:
        line = raw.rstrip("\r\n").strip()
        if line:
            yield line


def _iter_tail_lines(path: Path, poll_s: float = 0.2) -> Iterator[str]:
    position = 0
    buf = b""
    while True:
        if not path.exists():
            time.sleep(poll_s)
            continue

        try:
            size = path.stat().st_size
        except OSError:
            time.sleep(poll_s)
            continue
        if size < position:
            position = 0
            buf = b""

        try:
            with path.open("rb") as handle:
                handle.seek(position)
                chunk = handle.read()
                position = handle.tell()
        except OSError:
            time.sleep(poll_s)
            continue

        if not chunk:
            time.sleep(poll_s)
            continue

        buf += chunk
        while True:
            idx = buf.find(b"\n")
            if idx == -1:
                break
            raw_line = buf[:idx]
            buf = buf[idx + 1 :]
            text = raw_line.rstrip(b"\r").decode("utf-8", errors="replace").strip()
            if text:
                yield text


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish StreamTranscriptSegment events to Redis Streams (host-run)")
    parser.add_argument("--room-id", default="room:demo")
    parser.add_argument("--mode", choices=["tail", "stdin"], default="stdin")
    parser.add_argument("--path", default="data/transcripts/live.txt", help="Used for --mode tail")
    parser.add_argument("--redis-url", default=None, help="Override Redis URL (else REDIS_URL_HOST/REDIS_URL)")
    parser.add_argument("--transcripts-key", default=None, help="Override STREAM_TRANSCRIPTS_KEY")
    parser.add_argument("--confidence", type=float, default=None, help="Optional fixed confidence (0..1)")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    redis_url = _resolve_redis_url(args.redis_url)
    transcripts_key = args.transcripts_key or _opt_env("STREAM_TRANSCRIPTS_KEY", "stream:transcripts")
    if not redis_url:
        print("FAIL: missing redis url; set REDIS_URL_HOST/REDIS_URL or pass --redis-url")
        return 2
    if not transcripts_key:
        print("FAIL: missing transcripts stream key; set STREAM_TRANSCRIPTS_KEY or pass --transcripts-key")
        return 2

    if args.confidence is not None and not (0.0 <= args.confidence <= 1.0):
        print("FAIL: --confidence must be between 0 and 1")
        return 2

    try:
        client = _connect_redis(redis_url)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: Redis connection error ({redis_url}): {exc}")
        print("HINT: host scripts should usually use REDIS_URL_HOST=redis://127.0.0.1:6379/0")
        return 2

    if args.mode == "tail":
        tail_path = Path(args.path)
        if not tail_path.is_absolute():
            tail_path = REPO_ROOT / tail_path
        line_iter = _iter_tail_lines(tail_path)
        source_meta: Dict[str, Any] = {"mode": "tail", "path": str(tail_path)}
    else:
        line_iter = _iter_stdin_lines()
        source_meta = {"mode": "stdin"}

    print(
        json.dumps(
            {
                "ok": True,
                "room_id": args.room_id,
                "stream": transcripts_key,
                "redis_url": redis_url,
                **source_meta,
            },
            sort_keys=True,
        )
    )

    base_monotonic = time.monotonic()
    last_end_ms = 0
    seq = 1

    try:
        for text in line_iter:
            now_ms = int((time.monotonic() - base_monotonic) * 1000)
            start_ms = max(now_ms, last_end_ms)
            duration_ms = max(800, min(10_000, len(text) * 40))
            end_ms = start_ms + duration_ms
            last_end_ms = end_ms

            capture_ms = int(time.time() * 1000)
            seg_id = f"seg_{capture_ms}_{seq}"
            event: Dict[str, Any] = {
                "schema_name": "StreamTranscriptSegment",
                "schema_version": "1.0.0",
                "id": seg_id,
                "ts": _utc_now_iso(),
                "room_id": args.room_id,
                "start_ms": int(start_ms),
                "end_ms": int(end_ms),
                "text": text,
            }
            if args.confidence is not None:
                event["confidence"] = float(args.confidence)

            try:
                _validate_stream_transcript(event)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL: schema validation failed: {exc}")
                return 1

            try:
                redis_id = client.xadd(transcripts_key, {"data": json.dumps(event, ensure_ascii=False)})
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL: redis XADD failed: {exc}")
                return 2

            print(
                json.dumps(
                    {
                        "ok": True,
                        "schema_name": "StreamTranscriptSegment",
                        "seq": int(seq),
                        "start_ms": int(start_ms),
                        "end_ms": int(end_ms),
                        "redis_stream": transcripts_key,
                        "redis_id": redis_id,
                        "text": text,
                    },
                    sort_keys=True,
                )
            )
            seq += 1
    except KeyboardInterrupt:
        print("Stopped.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
