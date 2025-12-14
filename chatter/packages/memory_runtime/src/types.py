from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol


@dataclass
class MemoryItem:
    id: str
    ts: str
    scope: str
    scope_key: str
    category: str
    subject: str
    value: str
    confidence: float
    ttl_days: int
    source: Dict[str, Any]
    tags: Dict[str, Any] | None = field(default_factory=dict)
    redactions: List[str] | None = field(default_factory=list)
    expires_at: str | None = None
    version: int | None = None


@dataclass
class MemoryQueryResult:
    items: List[MemoryItem]
    meta: Dict[str, Any] | None = field(default_factory=dict)


class MemoryStore(Protocol):
    def search(self, scope_key: str, query: str, limit: int = 5) -> MemoryQueryResult:
        ...

    def upsert(self, scope_key: str, item: MemoryItem) -> None:
        ...

    def dump(self) -> Dict[str, List[MemoryItem]]:
        ...
