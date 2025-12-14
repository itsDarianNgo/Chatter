from __future__ import annotations

import hashlib
from pathlib import Path


def canonical_prompt_text(path: Path) -> str:
    """Load prompt text in a platform-independent canonical form.

    Normalizes newlines to ``\n`` and enforces exactly one trailing newline so
    sha256 digests are stable across OS newline conventions.
    """

    raw = path.read_text(encoding="utf-8", errors="strict")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.rstrip("\n") + "\n"
    return normalized


def canonical_prompt_sha256(path: Path) -> str:
    normalized = canonical_prompt_text(path)
    digest = hashlib.sha256(normalized.encode("utf-8"))
    return digest.hexdigest()
