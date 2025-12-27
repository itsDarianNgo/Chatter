from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional


@dataclass
class ObservationEntry:
    redis_id: str
    ts_ms: int
    observation: dict


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
        self.observations: Dict[str, List[ObservationEntry]] = {}
        self.auto_room_last_spoke: Dict[str, int] = {}
        self.auto_persona_last_spoke: Dict[str, int] = {}
        self.auto_dedupe: "OrderedDict[str, int]" = OrderedDict()
        self.auto_observation_counts: "OrderedDict[str, tuple[int, int]]" = OrderedDict()
        self.auto_last_observation_ids: Deque[str] = deque(maxlen=5)

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

    def record_auto_observation_id(self, obs_id: str) -> None:
        if obs_id:
            self.auto_last_observation_ids.append(obs_id)

    def auto_seen_before(self, obs_id: str, persona_id: str, now_ms: int, window_ms: int) -> bool:
        self._prune_auto_dedupe(now_ms, window_ms)
        key = f"{obs_id}:{persona_id}"
        if key in self.auto_dedupe:
            return True
        self.auto_dedupe[key] = now_ms
        self.auto_dedupe.move_to_end(key)
        return False

    def auto_observation_count(self, obs_id: str, now_ms: int, window_ms: int) -> int:
        self._prune_auto_observation_counts(now_ms, window_ms)
        entry = self.auto_observation_counts.get(obs_id)
        return entry[1] if entry else 0

    def record_auto_observation_message(self, obs_id: str, now_ms: int, window_ms: int) -> int:
        self._prune_auto_observation_counts(now_ms, window_ms)
        if obs_id in self.auto_observation_counts:
            first_seen, count = self.auto_observation_counts[obs_id]
            count += 1
            self.auto_observation_counts[obs_id] = (first_seen, count)
        else:
            self.auto_observation_counts[obs_id] = (now_ms, 1)
        self.auto_observation_counts.move_to_end(obs_id)
        return self.auto_observation_counts[obs_id][1]

    def auto_persona_ready(self, persona_id: str, now_ms: int, cooldown_ms: int) -> bool:
        if cooldown_ms <= 0:
            return True
        last_ms = self.auto_persona_last_spoke.get(persona_id)
        if last_ms is None:
            return True
        return now_ms - last_ms >= cooldown_ms

    def auto_room_ready(self, room_id: str, now_ms: int, rate_limit_ms: int) -> bool:
        if rate_limit_ms <= 0:
            return True
        last_ms = self.auto_room_last_spoke.get(room_id)
        if last_ms is None:
            return True
        return now_ms - last_ms >= rate_limit_ms

    def record_auto_publish(self, room_id: str, persona_id: str, now_ms: int) -> None:
        self.auto_room_last_spoke[room_id] = now_ms
        self.auto_persona_last_spoke[persona_id] = now_ms

    def _prune_auto_dedupe(self, now_ms: int, window_ms: int) -> None:
        if window_ms <= 0:
            self.auto_dedupe.clear()
            return
        while self.auto_dedupe:
            _, ts_ms = next(iter(self.auto_dedupe.items()))
            if now_ms - ts_ms <= window_ms:
                break
            self.auto_dedupe.popitem(last=False)

    def _prune_auto_observation_counts(self, now_ms: int, window_ms: int) -> None:
        if window_ms <= 0:
            self.auto_observation_counts.clear()
            return
        while self.auto_observation_counts:
            _, (ts_ms, _) = next(iter(self.auto_observation_counts.items()))
            if now_ms - ts_ms <= window_ms:
                break
            self.auto_observation_counts.popitem(last=False)

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

    def add_observation(
        self, room_id: str, entry: ObservationEntry, now_ms: int, max_age_ms: int, max_items: int
    ) -> int:
        entries = self.observations.setdefault(room_id, [])
        entries.append(entry)
        return self.prune_observations(room_id, now_ms, max_age_ms, max_items)

    def prune_observations(self, room_id: str, now_ms: int, max_age_ms: int, max_items: int) -> int:
        entries = self.observations.get(room_id, [])
        if not entries:
            return 0
        threshold = now_ms - max_age_ms
        kept = [entry for entry in entries if entry.ts_ms >= threshold]
        dropped_old = len(entries) - len(kept)
        kept.sort(key=lambda entry: (entry.ts_ms, entry.redis_id))
        if max_items > 0 and len(kept) > max_items:
            kept = kept[-max_items:]
        self.observations[room_id] = kept
        return dropped_old

    def get_recent_observations(
        self, room_id: str, now_ms: int, max_age_ms: int, max_items: int
    ) -> List[ObservationEntry]:
        self.prune_observations(room_id, now_ms, max_age_ms, max_items)
        return list(self.observations.get(room_id, []))

    def observations_total(self) -> int:
        return sum(len(entries) for entries in self.observations.values())


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
    observations_received: int = 0
    observations_valid: int = 0
    observations_invalid: int = 0
    observations_dropped_old: int = 0
    observations_buffered_total: int = 0
    observations_used_in_prompts: int = 0
    observations_chars_included: int = 0
    observations_last_used_ids: Deque[str] = field(default_factory=lambda: deque(maxlen=5))
    observations_last_used_count: int = 0
    observations_last_used_chars: int = 0
    observations_last_context_preview: str | None = None
    obs_context_config_path: str | None = None
    obs_context_max_items: int | None = None
    obs_context_max_age_ms: int | None = None
    obs_context_max_chars: int | None = None
    obs_context_prefix: str | None = None
    obs_context_format_version: str | None = None
    auto_commentary_enabled: bool = False
    auto_commentary_hype_threshold: float | None = None
    auto_commentary_persona_cooldown_ms: int | None = None
    auto_commentary_room_rate_limit_ms: int | None = None
    auto_obs_seen: int = 0
    auto_obs_interesting: int = 0
    auto_messages_attempted: int = 0
    auto_messages_published: int = 0
    auto_suppressed_cooldown: int = 0
    auto_suppressed_room_rate: int = 0
    auto_suppressed_dedupe: int = 0
    auto_generation_failed: int = 0
    auto_last_observation_ids: Deque[str] = field(default_factory=lambda: deque(maxlen=5))
    auto_last_decision: dict | None = None

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
            "observations_received": self.observations_received,
            "observations_valid": self.observations_valid,
            "observations_invalid": self.observations_invalid,
            "observations_dropped_old": self.observations_dropped_old,
            "observations_buffered_total": self.observations_buffered_total,
            "observations_used_in_prompts": self.observations_used_in_prompts,
            "observations_chars_included": self.observations_chars_included,
            "observations_last_used_ids": list(self.observations_last_used_ids),
            "observations_last_used_count": self.observations_last_used_count,
            "observations_last_used_chars": self.observations_last_used_chars,
            "observations_last_context_preview": self.observations_last_context_preview,
            "obs_context_config_path": self.obs_context_config_path,
            "obs_context_max_items": self.obs_context_max_items,
            "obs_context_max_age_ms": self.obs_context_max_age_ms,
            "obs_context_max_chars": self.obs_context_max_chars,
            "obs_context_prefix": self.obs_context_prefix,
            "obs_context_format_version": self.obs_context_format_version,
            "auto_commentary_enabled": self.auto_commentary_enabled,
            "auto_commentary_hype_threshold": self.auto_commentary_hype_threshold,
            "auto_commentary_persona_cooldown_ms": self.auto_commentary_persona_cooldown_ms,
            "auto_commentary_room_rate_limit_ms": self.auto_commentary_room_rate_limit_ms,
            "auto_obs_seen": self.auto_obs_seen,
            "auto_obs_interesting": self.auto_obs_interesting,
            "auto_messages_attempted": self.auto_messages_attempted,
            "auto_messages_published": self.auto_messages_published,
            "auto_suppressed_cooldown": self.auto_suppressed_cooldown,
            "auto_suppressed_room_rate": self.auto_suppressed_room_rate,
            "auto_suppressed_dedupe": self.auto_suppressed_dedupe,
            "auto_generation_failed": self.auto_generation_failed,
            "auto_last_observation_ids": list(self.auto_last_observation_ids),
            "auto_last_decision": self.auto_last_decision,
        }
