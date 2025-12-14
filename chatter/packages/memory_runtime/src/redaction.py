from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

DEFAULT_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("phone", r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    (
        "address",
        r"\b\d{1,5}\s+[A-Za-z]{2,}\s+(Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd)\b",
    ),
)


def _collect_patterns(policy: Dict) -> Iterable[Tuple[str, str]]:
    redaction_cfg = policy.get("redaction") or {}
    if not redaction_cfg.get("enabled", False):
        return []
    patterns: List[Tuple[str, str]] = list(DEFAULT_PATTERNS)
    for entry in redaction_cfg.get("patterns", []):
        name = entry.get("name") or "custom"
        regex = entry.get("regex")
        if regex:
            patterns.append((name, regex))
    return patterns


def apply_redactions(text: str, policy: Dict) -> Tuple[str, List[str]]:
    if not text:
        return "", []

    notes: List[str] = []
    redacted = text
    for name, pattern in _collect_patterns(policy):
        try:
            compiled = re.compile(pattern, flags=re.IGNORECASE)
            if compiled.search(redacted):
                redacted = compiled.sub("[REDACTED]", redacted)
                notes.append(name)
        except re.error:
            notes.append(f"invalid_pattern:{name}")
    return redacted, notes


def contains_disallowed_patterns(text: str, policy: Dict) -> bool:
    if not text:
        return False
    for _, pattern in _collect_patterns(policy):
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


__all__ = ["apply_redactions", "contains_disallowed_patterns", "DEFAULT_PATTERNS"]
