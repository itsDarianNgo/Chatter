from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from .mem0_client import Mem0Client
from .types import MemoryItem, MemoryQueryResult, MemoryStore

logger = logging.getLogger(__name__)


def _derive_scope_from_key(scope_key: str) -> str:
    if scope_key.startswith("persona_user"):
        return "persona_user"
    if scope_key.startswith("persona_room"):
        return "persona_room"
    if scope_key.startswith("persona"):
        return "persona"
    return "persona_room"


def _bucket_key_from_scope(scope_key: str) -> str:
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
    if prefix == "room":
        if len(parts) >= 4:
            return parts[-2]
        if len(parts) >= 3:
            return parts[-1]
    return scope_key


def _identifiers_from_scope_key(scope_key: str) -> Dict[str, str]:
    raw = (scope_key or "").strip()
    if not raw:
        return {}

    parts = raw.split(":")
    if not parts:
        return {}

    prefix = parts[0]
    if prefix == "persona" and len(parts) >= 2:
        persona_id = ":".join(parts[1:]).strip()
        if persona_id:
            return {"agent_id": persona_id}
        return {"user_id": raw}

    if prefix == "persona_room" and len(parts) >= 3:
        room_id = ":".join(parts[1:-1]).strip()
        persona_id = (parts[-1] or "").strip()
        identifiers: Dict[str, str] = {}
        if persona_id:
            identifiers["agent_id"] = persona_id
        if room_id:
            identifiers["run_id"] = room_id
        return identifiers or {"user_id": raw}

    if prefix == "persona_user" and len(parts) >= 4:
        room_id = ":".join(parts[1:-2]).strip()
        persona_id = (parts[-2] or "").strip()
        user_id = (parts[-1] or "").strip()
        identifiers = {}
        if user_id:
            identifiers["user_id"] = user_id
        if persona_id:
            identifiers["agent_id"] = persona_id
        if room_id:
            identifiers["run_id"] = room_id
        return identifiers or {"user_id": raw}

    # Legacy (pre-prefixed) scope keys.
    if prefix == "room" and len(parts) >= 3:
        if len(parts) >= 4:
            room_id = ":".join(parts[:-2]).strip()
            persona_id = (parts[-2] or "").strip()
            user_id = (parts[-1] or "").strip()
            identifiers = {}
            if user_id:
                identifiers["user_id"] = user_id
            if persona_id:
                identifiers["agent_id"] = persona_id
            if room_id:
                identifiers["run_id"] = room_id
            return identifiers or {"user_id": raw}

        room_id = ":".join(parts[:-1]).strip()
        persona_id = (parts[-1] or "").strip()
        identifiers = {}
        if persona_id:
            identifiers["agent_id"] = persona_id
        if room_id:
            identifiers["run_id"] = room_id
        return identifiers or {"user_id": raw}

    if ":" not in raw:
        return {"agent_id": raw}

    return {"user_id": raw}


class Mem0MemoryStore(MemoryStore):
    def __init__(self, client: Mem0Client, max_items: int = 5, max_chars: int = 800) -> None:
        self.client = client
        self.max_items = max_items
        self.max_chars = max_chars
        self._store: Dict[str, List[MemoryItem]] = {}

    def _fallback_id(self, scope_key: str, value: str, idx: int) -> str:
        digest = hashlib.sha256(f"{scope_key}:{value}:{idx}".encode("utf-8")).hexdigest()
        return f"mem0:{digest[:16]}"

    def _build_item(self, result: Dict[str, Any], scope_key: str, idx: int) -> MemoryItem:
        metadata = result.get("metadata") or {}
        raw_value = metadata.get("value") or result.get("memory") or result.get("content") or ""
        value = str(raw_value)[: self.max_chars]
        memory_id = result.get("id") or result.get("memory_id") or result.get("uuid")
        if not memory_id:
            memory_id = self._fallback_id(scope_key, value, idx)
        ts = metadata.get("ts") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        scope = metadata.get("scope") or _derive_scope_from_key(scope_key)
        subject = metadata.get("subject") or "memory"
        category = metadata.get("category") or "general"
        ttl_days = int(metadata.get("ttl_days") or 30)
        confidence = float(metadata.get("confidence") or result.get("score") or 0.5)
        schema_name = metadata.get("schema_name")
        schema_version = metadata.get("schema_version")
        source = metadata.get("source") or {"kind": "mem0_search", "memory_id": memory_id}

        payload = {
            "id": str(memory_id),
            "ts": ts,
            "scope": scope,
            "scope_key": metadata.get("scope_key") or scope_key,
            "category": str(category),
            "subject": str(subject),
            "value": value,
            "confidence": confidence,
            "ttl_days": ttl_days,
            "source": source,
            "schema_name": schema_name,
            "schema_version": schema_version,
        }

        tags = metadata.get("tags")
        if isinstance(tags, dict):
            payload["tags"] = tags

        redactions = metadata.get("redactions")
        if isinstance(redactions, list):
            payload["redactions"] = redactions

        return MemoryItem.from_dict(payload)

    def search(self, scope_key: str, query: str, limit: int = 5) -> MemoryQueryResult:
        identifiers = _identifiers_from_scope_key(scope_key)
        if not identifiers:
            raise ValueError("mem0_scope_key_invalid: cannot derive identifiers")

        payload = {"query": query, "limit": min(limit, self.max_items), **identifiers}
        response = self.client.search_memories(payload)
        results = response.get("results") or response.get("data") or []
        items: List[MemoryItem] = []
        for idx, result in enumerate(results):
            try:
                items.append(self._build_item(result, scope_key, idx))
            except Exception as exc:  # noqa: BLE001
                logger.debug("mem0 search item parse failed: %s", exc)
                continue
        meta = {"returned": len(items), "matched": len(results)}
        return MemoryQueryResult(items=items[: self.max_items], meta=meta)

    def upsert(self, scope_key: str, item: MemoryItem) -> None:
        if not item.scope_key:
            raise ValueError("scope_key_required")
        if item.scope_key != scope_key:
            raise ValueError("scope_key_mismatch")

        identifiers = _identifiers_from_scope_key(scope_key)
        if not identifiers:
            raise ValueError("mem0_scope_key_invalid: cannot derive identifiers")

        metadata = {
            "scope": item.scope,
            "scope_key": item.scope_key,
            "category": item.category,
            "subject": item.subject,
            "confidence": item.confidence,
            "ttl_days": item.ttl_days,
            "schema_name": item.schema_name,
            "schema_version": item.schema_version,
        }
        if item.tags:
            metadata["tags"] = item.tags
        if item.redactions:
            metadata["redactions"] = item.redactions

        payload = {"messages": [{"role": "user", "content": item.value}], "infer": False, "async_mode": False, "metadata": metadata, **identifiers}
        response = self.client.add_memory(payload)
        created_id = response.get("id") or response.get("memory_id")
        bucket_key = _bucket_key_from_scope(scope_key)
        bucket = self._store.setdefault(bucket_key, [])
        replaced = False
        for idx, existing in enumerate(bucket):
            if existing.id == item.id:
                bucket[idx] = item
                replaced = True
                break
        if not replaced:
            bucket.append(item)
        if created_id:
            logger.debug("mem0 upsert created id %s for scope %s", created_id, scope_key)

    def dump(self) -> Dict[str, List[MemoryItem]]:
        return self._store

    def delete(self, memory_id: str) -> None:
        self.client.delete_memory(memory_id)


__all__ = ["Mem0MemoryStore"]
