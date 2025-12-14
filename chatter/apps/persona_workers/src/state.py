from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional


@dataclass
class RoomState:
    room_id: str
    max_recent: int
    recent_messages: Deque[dict] = field(init=False)
    bot_budget_window_ms: int = 10_000
    bot_budget_limit: int = 5
    bot_publish_times: Deque[int] = field(init=False)
    event_times: Deque[int] = field(init=False)

    def __post_init__(self) -> None:
        self.recent_messages = deque(maxlen=self.max_recent)
        self.bot_publish_times = deque()
        self.event_times = deque()

    def add_message(self, message: dict) -> None:
        minimal = {
            "id": message.get("id"),
            "ts": message.get("ts"),
            "origin": message.get("origin"),
            "user_id": message.get("user_id"),
            "display_name": message.get("display_name"),
            "content": message.get("content"),
        }
        self.recent_messages.append(minimal)

    def record_bot_publish(self, now_ms: int) -> None:
        self.bot_publish_times.append(now_ms)
        self._prune_budget(now_ms)

    def record_event(self, ts_ms: int) -> None:
        self.event_times.append(ts_ms)
        self._prune_events(ts_ms)

    def within_budget(self, now_ms: int) -> bool:
        self._prune_budget(now_ms)
        return len(self.bot_publish_times) < self.bot_budget_limit

    def rate_10s(self, now_ms: int) -> int:
        self._prune_events(now_ms)
        return len(self.event_times)

    def _prune_budget(self, now_ms: int) -> None:
        while self.bot_publish_times and now_ms - self.bot_publish_times[0] > self.bot_budget_window_ms:
            self.bot_publish_times.popleft()

    def _prune_events(self, now_ms: int) -> None:
        window_ms = 10_000
        while self.event_times and now_ms - self.event_times[0] > window_ms:
            self.event_times.popleft()


@dataclass
class PersonaStats:
    persona_id: str
    last_spoke_at_ms: Optional[int] = None
    messages_published: int = 0
    mention_events: Deque[int] = field(default_factory=lambda: deque())

    def record_mention(self, ts_ms: int) -> None:
        self.mention_events.append(ts_ms)
        self._prune_mentions(ts_ms)

    def mentions_last_30s(self, now_ms: int) -> int:
        self._prune_mentions(now_ms)
        return len(self.mention_events)

    def _prune_mentions(self, now_ms: int) -> None:
        window_ms = 30_000
        while self.mention_events and now_ms - self.mention_events[0] > window_ms:
            self.mention_events.popleft()


class State:
    def __init__(self, max_recent: int, dedupe_size: int) -> None:
        self.max_recent = max_recent
        self.dedupe_size = dedupe_size
        self.dedupe_cache: "OrderedDict[str, None]" = OrderedDict()
        self.rooms: Dict[str, RoomState] = {}
        self.persona_stats: Dict[str, PersonaStats] = {}

    def get_room_state(self, room_id: str, budget_limit: int, budget_window_ms: int) -> RoomState:
        if room_id not in self.rooms:
            state = RoomState(room_id=room_id, max_recent=self.max_recent)
            state.bot_budget_limit = budget_limit
            state.bot_budget_window_ms = budget_window_ms
            self.rooms[room_id] = state
        return self.rooms[room_id]

    def get_persona_stats(self, persona_id: str) -> PersonaStats:
        if persona_id not in self.persona_stats:
            self.persona_stats[persona_id] = PersonaStats(persona_id=persona_id)
        return self.persona_stats[persona_id]

    def seen_before(self, message_id: str) -> bool:
        if message_id in self.dedupe_cache:
            return True
        self.dedupe_cache[message_id] = None
        self.dedupe_cache.move_to_end(message_id)
        if len(self.dedupe_cache) > self.dedupe_size:
            self.dedupe_cache.popitem(last=False)
        return False

    def add_recent_message(self, room_id: str, message: dict, budget_limit: int, budget_window_ms: int) -> None:
        room_state = self.get_room_state(room_id, budget_limit, budget_window_ms)
        room_state.add_message(message)

    def record_publish(self, room_id: str, now_ms: int, budget_limit: int, budget_window_ms: int) -> None:
        room_state = self.get_room_state(room_id, budget_limit, budget_window_ms)
        room_state.record_bot_publish(now_ms)

    def record_event(self, room_id: str, ts_ms: int, origin: str, budget_limit: int, budget_window_ms: int) -> None:
        room_state = self.get_room_state(room_id, budget_limit, budget_window_ms)
        room_state.record_event(ts_ms)

    def get_room_rate_10s(self, room_id: str, now_ms: int, budget_limit: int, budget_window_ms: int) -> int:
        room_state = self.get_room_state(room_id, budget_limit, budget_window_ms)
        return room_state.rate_10s(now_ms)


RuntimeState = State


@dataclass
class Stats:
    messages_consumed: int = 0
    messages_deduped: int = 0
    messages_published: int = 0
    messages_suppressed_cooldown: int = 0
    messages_suppressed_budget: int = 0
    messages_suppressed_bot_origin: int = 0
    last_decision_reasons: Dict[str, str] = field(default_factory=dict)
    decisions_by_reason: Dict[str, int] = field(default_factory=dict)
    last_decisions: Deque[dict] = field(default_factory=lambda: deque(maxlen=20))
    memory_enabled: bool = False
    memory_backend: str | None = None
    memory_policy_path: str | None = None
    memory_fixtures_path: str | None = None
    memory_items_total: int = 0
    memory_items_by_scope: Dict[str, int] = field(default_factory=dict)
    memory_reads_attempted: int = 0
    memory_reads_succeeded: int = 0
    memory_reads_failed: int = 0
    memory_writes_attempted: int = 0
    memory_writes_accepted: int = 0
    memory_writes_rejected: int = 0
    memory_writes_redacted: int = 0
    memory_writes_failed: int = 0
    memory_extract_strategy: str | None = None
    memory_llm_provider: str | None = None
    memory_llm_model: str | None = None
    memory_extract_llm_attempted: int = 0
    memory_extract_llm_succeeded: int = 0
    memory_extract_llm_failed: int = 0
    last_memory_extract_error: str | None = None
    mem0_base_url: str | None = None
    mem0_org_configured: bool = False
    mem0_project_configured: bool = False
    last_memory_read_ids: Deque[str] = field(default_factory=lambda: deque(maxlen=10))
    last_memory_write_ids: Deque[str] = field(default_factory=lambda: deque(maxlen=10))
    last_memory_error: str | None = None

    def record_decision(self, persona_id: str, reason: str, tags: Optional[dict] = None) -> None:
        tags = tags or {}
        self.decisions_by_reason[reason] = self.decisions_by_reason.get(reason, 0) + 1
        decision = {
            "persona_id": persona_id,
            "reason": reason,
        }
        if tags:
            decision.update(tags)
        self.last_decisions.append(
            {
                "ts_ms": tags.get("ts_ms"),
                **decision,
            }
        )

    def as_dict(self, enabled_personas: List[str], room_id: str) -> dict:
        return {
            "messages_consumed": self.messages_consumed,
            "messages_deduped": self.messages_deduped,
            "messages_published": self.messages_published,
            "messages_suppressed_cooldown": self.messages_suppressed_cooldown,
            "messages_suppressed_budget": self.messages_suppressed_budget,
            "messages_suppressed_bot_origin": self.messages_suppressed_bot_origin,
            "last_decision_reasons": self.last_decision_reasons,
            "decisions_by_reason": self.decisions_by_reason,
            "recent_decisions": list(self.last_decisions),
            "enabled_personas": enabled_personas,
            "room_id": room_id,
            "memory_enabled": self.memory_enabled,
            "memory_backend": self.memory_backend,
            "memory_policy_path": self.memory_policy_path,
            "memory_fixtures_path": self.memory_fixtures_path,
            "memory_items_total": self.memory_items_total,
            "memory_items_by_scope": self.memory_items_by_scope,
            "memory_reads_attempted": self.memory_reads_attempted,
            "memory_reads_succeeded": self.memory_reads_succeeded,
            "memory_reads_failed": self.memory_reads_failed,
            "memory_writes_attempted": self.memory_writes_attempted,
            "memory_writes_accepted": self.memory_writes_accepted,
            "memory_writes_rejected": self.memory_writes_rejected,
            "memory_writes_redacted": self.memory_writes_redacted,
            "memory_writes_failed": self.memory_writes_failed,
            "memory_extract_strategy": self.memory_extract_strategy,
            "memory_llm_provider": self.memory_llm_provider,
            "memory_llm_model": self.memory_llm_model,
            "memory_extract_llm_attempted": self.memory_extract_llm_attempted,
            "memory_extract_llm_succeeded": self.memory_extract_llm_succeeded,
            "memory_extract_llm_failed": self.memory_extract_llm_failed,
            "mem0_base_url": self.mem0_base_url,
            "mem0_org_configured": self.mem0_org_configured,
            "mem0_project_configured": self.mem0_project_configured,
            "last_memory_read_ids": list(self.last_memory_read_ids),
            "last_memory_write_ids": list(self.last_memory_write_ids),
            "last_memory_extract_error": self.last_memory_extract_error,
            "last_memory_error": self.last_memory_error,
        }
