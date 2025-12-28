from __future__ import annotations

import hashlib
import re
from typing import Iterable, Sequence

from .auto_commentary import AutoCommentaryConfig
from .state import RuntimeState


def _normalize_tokens(items: Iterable[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = str(item).strip().lower()
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return normalized


def _normalize_summary(text: str, normalize: bool) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if normalize:
        cleaned = cleaned.lower()
        cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def compute_summary_hash(observation: dict, cfg: AutoCommentaryConfig) -> str:
    summary = str(observation.get("summary") or "")
    normalized = _normalize_summary(summary, cfg.summary_dedupe.normalize)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def dedupe_key(observation: dict, cfg: AutoCommentaryConfig) -> str:
    obs_id = str(observation.get("id") or "")
    if not cfg.summary_dedupe.enabled:
        return obs_id
    summary_hash = compute_summary_hash(observation, cfg)
    if summary_hash and obs_id:
        return f"{obs_id}:{summary_hash}"
    return obs_id or summary_hash


def compute_interest_score(observation: dict, cfg: AutoCommentaryConfig) -> float:
    hype = observation.get("hype_level")
    hype_value = float(hype) if isinstance(hype, (int, float)) else 0.0
    hype_value = max(0.0, min(1.0, hype_value))

    tags = set(_normalize_tokens(observation.get("tags") if isinstance(observation.get("tags"), list) else []))
    entities = _normalize_tokens(
        observation.get("entities") if isinstance(observation.get("entities"), list) else []
    )

    score = hype_value * cfg.interest_weights.hype
    if entities:
        score += cfg.interest_weights.mentions

    entity_factor = min(len(entities), 3) / 3.0 if entities else 0.0
    score += entity_factor * cfg.interest_weights.entities

    if "hype" in tags:
        score += cfg.interest_weights.tag_hype

    return float(score)


def _is_interesting(observation: dict, cfg: AutoCommentaryConfig, score: float) -> tuple[bool, str]:
    hype = observation.get("hype_level")
    hype_value = float(hype) if isinstance(hype, (int, float)) else 0.0
    if hype_value >= cfg.hype_threshold:
        return True, "hype"

    tag_values = observation.get("tags") if isinstance(observation.get("tags"), list) else []
    tags = set(_normalize_tokens(tag_values))
    if tags and cfg.trigger_tags and tags.intersection(cfg.trigger_tags):
        return True, "tag"

    if cfg.trigger_on_entities:
        entities = observation.get("entities") if isinstance(observation.get("entities"), list) else []
        if any(str(ent).strip() for ent in entities):
            return True, "entities"

    if score >= cfg.hype_threshold:
        return True, "score"

    return False, "not_interesting"


def should_emit(
    observation: dict, state: RuntimeState, cfg: AutoCommentaryConfig, now_ms: int
) -> tuple[bool, str, float]:
    score = compute_interest_score(observation, cfg)
    interesting, reason = _is_interesting(observation, cfg, score)
    if not interesting:
        return False, "not_interesting", score

    room_id = str(observation.get("room_id") or "")
    ok, momentum_reason = state.auto_room_momentum_ready(
        room_id,
        now_ms,
        cfg.momentum_window_ms,
        cfg.momentum_max_msgs,
        cfg.momentum_min_interval_ms,
    )
    if not ok:
        return False, momentum_reason, score

    if not state.auto_room_ready(room_id, now_ms, cfg.room_rate_limit_ms):
        return False, "room_rate", score

    obs_id = str(observation.get("id") or "")
    if cfg.max_messages_per_observation > 0 and obs_id:
        count = state.auto_observation_count(obs_id, now_ms, cfg.dedupe_window_ms)
        if count >= cfg.max_messages_per_observation:
            return False, "max_per_observation", score

    if cfg.summary_dedupe.enabled:
        summary_hash = compute_summary_hash(observation, cfg)
        if summary_hash and state.auto_summary_seen_before(summary_hash, now_ms, cfg.summary_dedupe.ttl_ms):
            return False, "summary_dedupe", score

    return True, "ok", score


def _selection_score(seed: str) -> float:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def _extract_mentions(observation: dict, persona_ids: Sequence[str]) -> set[str]:
    entities = _normalize_tokens(
        observation.get("entities") if isinstance(observation.get("entities"), list) else []
    )
    entity_set = set(entities)
    summary = str(observation.get("summary") or "").lower()
    mentioned: set[str] = set()

    for persona_id in persona_ids:
        pid = persona_id.lower()
        if pid in entity_set:
            mentioned.add(persona_id)
            continue
        if f"@{pid}" in summary:
            mentioned.add(persona_id)
            continue
        if re.search(rf"\b{re.escape(pid)}\b", summary):
            mentioned.add(persona_id)

    return mentioned


def pick_persona(
    observation: dict,
    state: RuntimeState,
    cfg: AutoCommentaryConfig,
    enabled_personas: Sequence[str],
) -> tuple[str | None, str]:
    persona_ids = sorted({str(pid) for pid in enabled_personas if str(pid).strip()})
    if not persona_ids:
        return None, "no_persona"

    room_id = str(observation.get("room_id") or "")
    obs_id = str(observation.get("id") or "")
    seed_base = obs_id or str(observation.get("summary") or "") or "obs"

    avoid_last_n = max(0, cfg.persona_diversity.avoid_repeat_last_n)
    recent = state.auto_recent_personas(room_id, avoid_last_n)
    candidates = persona_ids
    diversity_reason = "deterministic"
    if avoid_last_n > 0:
        filtered = [pid for pid in persona_ids if pid not in recent]
        if filtered:
            candidates = filtered
            diversity_reason = "diversity_filtered"
        else:
            diversity_reason = "diversity_fallback"

    mentioned = _extract_mentions(observation, persona_ids) if cfg.mention_targeting.enabled else set()

    best_id = None
    best_score = -1.0
    for persona_id in candidates:
        seed = f"{seed_base}:{room_id}:{persona_id}"
        score = _selection_score(seed)
        if persona_id in mentioned:
            score += cfg.mention_targeting.boost
        if score > best_score or (score == best_score and (best_id is None or persona_id < best_id)):
            best_score = score
            best_id = persona_id

    if best_id is None:
        return None, "diversity" if diversity_reason == "diversity_fallback" else "no_persona"

    if best_id in mentioned:
        return best_id, "mention_targeted"
    return best_id, diversity_reason
