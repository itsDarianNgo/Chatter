#!/usr/bin/env python
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional


def _which(name: str) -> Optional[str]:
    path = shutil.which(name)
    return str(path) if path else None


def _run_version(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else ""


def main() -> int:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        print("SKIP: ffmpeg not installed (ffmpeg not found on PATH)")
        return 0

    whisper_py_ok = False
    try:
        import whisper  # type: ignore  # noqa: F401
    except Exception:
        whisper_py_ok = False
    else:
        whisper_py_ok = True

    whisper_bin = os.getenv("WHISPER_CPP_BIN")
    if whisper_bin and not os.path.exists(whisper_bin):
        whisper_bin = None

    whisper_cli = _which("whisper") or _which("whisper-cli") or _which("whispercpp")
    whisper_ok = whisper_py_ok or bool(whisper_bin) or bool(whisper_cli)

    if not whisper_ok:
        print("SKIP: whisper not installed (install openai-whisper or whisper.cpp)")
        return 0

    ffmpeg_version = _run_version([ffmpeg, "-version"])
    whisper_version = ""
    if whisper_cli:
        whisper_version = _run_version([whisper_cli, "--help"])
    elif whisper_bin:
        whisper_version = _run_version([whisper_bin, "--help"])

    parts = ["PASS: asr deps present"]
    if ffmpeg_version:
        parts.append(f"ffmpeg={ffmpeg_version}")
    if whisper_py_ok:
        parts.append("whisper=python")
    elif whisper_cli:
        parts.append(f"whisper={whisper_cli}")
    elif whisper_bin:
        parts.append(f"whisper={whisper_bin}")
    if whisper_version:
        parts.append(f"whisper_hint={whisper_version}")

    print(" | ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

