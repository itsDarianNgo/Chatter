from __future__ import annotations

import unittest

from .mem0_store import Mem0MemoryStore, _identifiers_from_scope_key
from .types import MemoryItem


class _DummyMem0Client:
    def __init__(self) -> None:
        self.last_add_payload: dict | None = None
        self.last_search_payload: dict | None = None
        self.last_deleted_id: str | None = None

    def add_memory(self, payload: dict) -> dict:
        self.last_add_payload = payload
        return {}

    def search_memories(self, payload: dict) -> dict:
        self.last_search_payload = payload
        return {"results": []}

    def delete_memory(self, memory_id: str) -> None:
        self.last_deleted_id = memory_id


def _make_item(scope_key: str, scope: str) -> MemoryItem:
    return MemoryItem(
        id="test123456",
        ts="2024-01-01T00:00:00Z",
        scope=scope,
        scope_key=scope_key,
        category="room_lore",
        subject="room",
        value="hello",
        confidence=0.5,
        ttl_days=30,
        source={"kind": "manual", "message_id": None, "user_id": None, "origin": "system"},
    )


class Mem0StoreIdentifierTests(unittest.TestCase):
    def test_identifiers_from_scope_key_prefixed(self) -> None:
        self.assertEqual(_identifiers_from_scope_key("persona:Alice"), {"agent_id": "Alice"})
        self.assertEqual(
            _identifiers_from_scope_key("persona_room:room:demo:Alice"),
            {"agent_id": "Alice", "run_id": "room:demo"},
        )
        self.assertEqual(
            _identifiers_from_scope_key("persona_user:room:demo:Alice:user123"),
            {"agent_id": "Alice", "run_id": "room:demo", "user_id": "user123"},
        )

    def test_identifiers_from_scope_key_legacy(self) -> None:
        self.assertEqual(_identifiers_from_scope_key("Alice"), {"agent_id": "Alice"})
        self.assertEqual(
            _identifiers_from_scope_key("room:demo:Alice"),
            {"agent_id": "Alice", "run_id": "room:demo"},
        )
        self.assertEqual(
            _identifiers_from_scope_key("room:demo:Alice:user123"),
            {"agent_id": "Alice", "run_id": "room:demo", "user_id": "user123"},
        )

    def test_store_sends_identifiers_for_add_and_search(self) -> None:
        client = _DummyMem0Client()
        store = Mem0MemoryStore(client)

        scope_key = "persona_room:room:demo:Alice"
        store.search(scope_key, "hello", limit=3)
        assert client.last_search_payload is not None
        self.assertEqual(client.last_search_payload.get("agent_id"), "Alice")
        self.assertEqual(client.last_search_payload.get("run_id"), "room:demo")
        self.assertNotIn("filters", client.last_search_payload)

        item = _make_item(scope_key, scope="persona_room")
        store.upsert(scope_key, item)
        assert client.last_add_payload is not None
        self.assertEqual(client.last_add_payload.get("agent_id"), "Alice")
        self.assertEqual(client.last_add_payload.get("run_id"), "room:demo")
        self.assertNotIn("filters", client.last_add_payload)
        self.assertNotIn("user_id", client.last_add_payload)
        self.assertEqual(client.last_add_payload.get("metadata", {}).get("scope_key"), scope_key)


if __name__ == "__main__":
    unittest.main()

