import re
from typing import Iterable

import re
from typing import Iterable

HYPE_TOKENS = {"POG", "POGGERS", "OMEGALUL", "LUL", "KEKW", "W", "HYPE"}


def sanitize_text(value: str) -> str:
    sanitized = value.replace("\n", " ").replace("\r", " ")
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = sanitized.strip()
    return sanitized


def strip_mentions(value: str) -> str:
    return re.sub(r"@\w+", "", value)


def truncate(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return value[:max_chars]
    return value[: max_chars - 1] + "…"


def detect_mentions(content: str, display_name: str) -> bool:
    lowered = content.lower()
    tokens = [display_name.lower()] if display_name else []
    if display_name and not display_name.startswith("@"):
        tokens.append(f"@{display_name.lower()}")
    return any(token in lowered for token in tokens if token)


def detect_hype_tokens(content: str) -> bool:
    upper = content.upper()
    return any(token in upper for token in HYPE_TOKENS)


def choose_from_list(items: Iterable[str], idx: int) -> str:
    items_list = list(items)
    if not items_list:
        return ""
    return items_list[idx % len(items_list)]
