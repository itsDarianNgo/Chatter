import time
from datetime import datetime, timezone
from typing import Tuple

from .state import RuntimeState

TRIGGERS = ["E2E_TEST_", "E2E_MARKER_", "@ClipGoblin"]


def _parse_ts(ts: str) -> datetime:
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def should_speak(
    room_id: str,
    persona_id: str,
    last_message: dict,
    state: RuntimeState,
    *,
    max_react_age_s: float,
    persona_cooldown_ms: int,
    budget_limit: int,
    budget_window_ms: int,
) -> Tuple[bool, str]:
    now = datetime.now(timezone.utc)
    ts_str = last_message.get("ts")
    msg_ts = _parse_ts(ts_str) if ts_str else now
    age_s = (now - msg_ts).total_seconds()
    if age_s > max_react_age_s:
        return False, "too_old"

    if last_message.get("origin") == "bot":
        return False, "bot_origin"

    persona_stats = state.get_persona_stats(persona_id)
    if persona_stats.last_spoke_at_ms is not None:
        delta_ms = (time.time() * 1000) - persona_stats.last_spoke_at_ms
        if delta_ms < persona_cooldown_ms:
            return False, "cooldown"

    content = last_message.get("content", "") or ""
    if not any(trigger in content for trigger in TRIGGERS):
        return False, "no_trigger"

    room_state = state.get_room_state(room_id, budget_limit, budget_window_ms)
    if not room_state.within_budget(int(time.time() * 1000)):
        return False, "budget"

    return True, "triggered"
