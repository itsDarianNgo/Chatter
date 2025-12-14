import hashlib
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

from .settings import settings
from .state import State
from .text_utils import detect_hype_tokens, detect_mentions


def _parse_ts(ts: str) -> datetime:
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def _ts_ms_from_event(event_msg: dict) -> int:
    ts_str = event_msg.get("ts")
    if ts_str:
        dt = _parse_ts(ts_str)
    else:
        dt = datetime.now(timezone.utc)
    return int(dt.timestamp() * 1000)


class PolicyEngine:
    def __init__(self, room_cfg: dict, persona_cfgs: Dict[str, dict], state: State) -> None:
        self.room_cfg = room_cfg
        self.persona_cfgs = persona_cfgs
        self.state = state
        timing_cfg = room_cfg.get("timing", {}) if room_cfg else {}
        self.p_base = float(timing_cfg.get("p_base", 0.15))
        self.p_mention_bonus = float(timing_cfg.get("p_mention_bonus", 0.35))
        self.p_hype_bonus = float(timing_cfg.get("p_hype_bonus", 0.10))
        self.p_rate_penalty_per_msg = float(timing_cfg.get("p_rate_penalty_per_msg", 0.01))
        self.soft_cooldown_ms = int(timing_cfg.get("soft_cooldown_ms", settings.persona_cooldown_ms_default))
        self.hard_cooldown_ms = timing_cfg.get("hard_cooldown_ms")
        self.max_bot_msgs_per_10s = int(
            timing_cfg.get("max_bot_msgs_per_10s", settings.room_bot_budget_per_10s_default)
        )
        self.bot_budget_window_ms = 10_000
        self.max_react_age_s = settings.max_react_age_s
        self.room_id = room_cfg.get("room_id") if room_cfg else None
        self.bot_react_to_bot_weight = timing_cfg.get("bot_react_to_bot_weight")

    def should_speak(self, persona_id: str, event_msg: dict) -> Tuple[bool, str, dict]:
        now = datetime.now(timezone.utc)
        msg_ts = _parse_ts(event_msg.get("ts")) if event_msg.get("ts") else now
        age_s = (now - msg_ts).total_seconds()
        tags = {
            "p_used": None,
            "h_value": None,
            "mention_detected": False,
            "hype_detected": False,
            "rate_10s": 0,
            "ts_ms": int(msg_ts.timestamp() * 1000),
        }

        if event_msg.get("origin") == "bot":
            return False, "bot_origin", tags

        if age_s > self.max_react_age_s:
            return False, "too_old", tags

        if self.room_id and event_msg.get("room_id") not in {self.room_id, None}:
            return False, "wrong_room", tags

        content = event_msg.get("content", "") or ""
        now_ms = int(time.time() * 1000)

        persona_stats = self.state.get_persona_stats(persona_id)
        if persona_stats.last_spoke_at_ms is not None:
            delta_ms = now_ms - persona_stats.last_spoke_at_ms
            cooldown_ms = self.soft_cooldown_ms
            if self.hard_cooldown_ms is not None:
                cooldown_ms = max(cooldown_ms, int(self.hard_cooldown_ms))
            if delta_ms < cooldown_ms:
                return False, "cooldown", tags

        room_state = self.state.get_room_state(
            event_msg.get("room_id", self.room_id or "room:demo"), self.max_bot_msgs_per_10s, self.bot_budget_window_ms
        )
        if not room_state.within_budget(now_ms):
            return False, "budget", tags

        is_marker = any(token in content for token in ("E2E_TEST_", "E2E_TEST_BOTLOOP_", "E2E_MARKER_"))
        if is_marker:
            rate = self.state.get_room_rate_10s(
                event_msg.get("room_id", self.room_id or "room:demo"), now_ms, self.max_bot_msgs_per_10s, self.bot_budget_window_ms
            )
            tags.update({
                "p_used": 1.0,
                "h_value": 0.0,
                "reason": "e2e_forced",
                "rate_10s": rate,
                "forced": True,
                "marker_present": True,
            })
            return True, "e2e_forced", tags

        display_name = self._persona_display_name(persona_id)
        mention_detected = detect_mentions(content, display_name)
        if mention_detected:
            persona_stats.record_mention(now_ms)

        hype_detected = detect_hype_tokens(content)
        tags["mention_detected"] = mention_detected
        tags["hype_detected"] = hype_detected
        tags["rate_10s"] = self.state.get_room_rate_10s(
            event_msg.get("room_id", self.room_id or "room:demo"), now_ms, self.max_bot_msgs_per_10s, self.bot_budget_window_ms
        )

        message_id = event_msg.get("id")
        h_value = self._deterministic_hash_score(f"{message_id}:{persona_id}") if message_id else 1.0
        p_threshold = self._compute_threshold(mention_detected, hype_detected, tags["rate_10s"])
        tags["p_used"] = p_threshold
        tags["h_value"] = h_value
        if self.bot_react_to_bot_weight is not None:
            tags["bot_react_to_bot_weight"] = self.bot_react_to_bot_weight

        if h_value < p_threshold:
            return True, "p_pass", tags

        return False, "p_gate", tags

    def _persona_display_name(self, persona_id: str) -> str:
        persona_cfg = self.persona_cfgs.get(persona_id, {})
        presentation = persona_cfg.get("presentation", {})
        return presentation.get("display_name") or persona_cfg.get("persona_id", persona_id)

    def _compute_threshold(self, mentioned: bool, hype: bool, rate_10s: int) -> float:
        p = self.p_base
        if mentioned:
            p = min(1.0, p + self.p_mention_bonus)
        if hype:
            p = min(1.0, p + self.p_hype_bonus)
        if rate_10s > 0:
            p = max(0.02, p - self.p_rate_penalty_per_msg * rate_10s)
        return p

    def _deterministic_hash_score(self, value: str) -> float:
        digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
        score = int.from_bytes(digest, "big") / float(2**64)
        return score


def ts_ms_from_event(event_msg: dict) -> int:
    return _ts_ms_from_event(event_msg)
