from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from .types import MemoryItem, MemoryQueryResult, MemoryStore
from .validate import validate_memory_item_dict, validate_memory_stub_fixtures

ISO_FORMATS: Tuple[str, ...] = ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _persona_key_from_scope(scope_key: str) -> str:
    parts = scope_key.split(":")
    if not parts:
        return scope_key
    prefix = parts[0]
    if prefix == "persona":
        return parts[-1]
    if prefix == "persona_room":
        return parts[-1]
    if prefix == "persona_user" and len(parts) >= 2:
        return parts[-2]
    return scope_key


def _parse_ts(ts: str) -> datetime:
    for fmt in ISO_FORMATS:
        try:
            if fmt.endswith("%z") and ts.endswith("Z"):
                ts = ts[:-1] + "+0000"
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return datetime.min


def _score_item(item: MemoryItem, query: str) -> Tuple[int, datetime, str]:
    tokens = [tok for tok in re.split(r"\W+", query.lower().strip()) if tok]
    if not tokens:
        tokens = []
    score = 0
    subject_l = item.subject.lower()
    value_l = item.value.lower()
    category_l = item.category.lower()
    for tok in tokens or [""]:
        if tok and tok in subject_l:
            score += 3
        if tok and tok in value_l:
            score += 2
        if tok and tok in category_l:
            score += 1
    return score, _parse_ts(item.ts), item.id


class StubMemoryStore(MemoryStore):
    def __init__(self, fixtures_path: Path | None = None):
        self._store: Dict[str, List[MemoryItem]] = {}
        if fixtures_path:
            self._load_fixtures(fixtures_path)

    def _load_fixtures(self, fixtures_path: Path) -> None:
        payload = _load_json(fixtures_path)
        validate_memory_stub_fixtures(payload)
        personas = payload.get("personas", {})
        for persona_id, items in personas.items():
            for raw in items:
                validate_memory_item_dict(raw)
                item = MemoryItem(**raw)
                self._store.setdefault(persona_id, []).append(item)

    def search(self, scope_key: str, query: str, limit: int = 5) -> MemoryQueryResult:
        matches: List[Tuple[int, datetime, str, MemoryItem]] = []
        for persona_items in self._store.values():
            for item in persona_items:
                if item.scope_key != scope_key:
                    continue
                score, ts_parsed, item_id = _score_item(item, query)
                if score > 0:
                    matches.append((score, ts_parsed, item_id, item))

        matches.sort(key=lambda tup: (-tup[0], -tup[1].timestamp(), tup[2]))
        limited = [entry[3] for entry in matches[:limit]]
        meta = {"returned": len(limited), "matched": len(matches)}
        return MemoryQueryResult(items=limited, meta=meta)

    def upsert(self, scope_key: str, item: MemoryItem) -> None:
        if item.scope_key != scope_key:
            return
        bucket_key = _persona_key_from_scope(scope_key)
        bucket = self._store.setdefault(bucket_key, [])
        for idx, existing in enumerate(bucket):
            if existing.id == item.id:
                bucket[idx] = item
                break
        else:
            bucket.append(item)

    def dump(self) -> Dict[str, List[MemoryItem]]:
        return self._store


__all__ = ["StubMemoryStore"]
