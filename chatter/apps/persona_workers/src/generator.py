import hashlib
import re
from typing import Dict

from .text_utils import choose_from_list, sanitize_text, strip_mentions, truncate

DEFAULT_EMOTES = ["Kappa", "PogChamp", "FeelsOkayMan", "OMEGALUL"]
TEMPLATE_FAMILIES = [
    ["lol", "true", "nah", "W", "L", "real"],
    ["POGGERS", "W PLAY", "HYPE", "LET'S GO"],
    ["nice", "solid", "clean", "ok then"],
    ["what happened?", "for real?", "actually?"],
]


def _deterministic_index(seed: str, modulo: int) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % modulo


def _extract_marker(content: str) -> str:
    for token in ("E2E_TEST_BOTLOOP_", "E2E_TEST_", "E2E_MARKER_"):
        if token in content:
            return token
    return ""


def _sanitize_echo(content: str) -> str:
    words = re.sub(r"[^\w\s]", " ", content).split()
    if not words:
        return ""
    return " ".join(words[:3])


def _maybe_add_emote(base: str, persona_id: str, event_id: str, room_cfg: dict, max_chars: int) -> str:
    emote_list = room_cfg.get("emote_policy", {}).get("allowed_emotes") or DEFAULT_EMOTES
    idx_seed = f"{event_id}:{persona_id}:emote"
    emote_idx = _deterministic_index(idx_seed, len(emote_list))
    include_emote = _deterministic_index(f"{idx_seed}:flip", 2) == 0
    if include_emote:
        candidate = f"{base} {emote_list[emote_idx]}".strip()
        candidate = truncate(candidate, max_chars)
        return candidate
    return base


def generate_reply(persona_cfg: Dict, room_cfg: dict, event_msg: Dict, state, tags: Dict) -> str:
    persona_id = persona_cfg.get("persona_id", "persona")
    content = event_msg.get("content", "") or ""
    max_chars = persona_cfg.get("safety", {}).get("max_chars", 200)
    marker = _extract_marker(content)
    reason = tags.get("reason") if tags else None
    event_id = event_msg.get("id", "evt")

    if reason == "e2e_forced" or marker:
        token = marker or "E2E_MARKER_"
        reply = f"got it: {token} ✅"
    else:
        tpl_seed = f"{event_id}:{persona_id}:tpl"
        tpl_family_idx = _deterministic_index(tpl_seed, len(TEMPLATE_FAMILIES) + 1)
        templates = TEMPLATE_FAMILIES[tpl_family_idx % len(TEMPLATE_FAMILIES)]
        reply_seed_idx = _deterministic_index(f"{tpl_seed}:choice", len(templates))
        base_reply = choose_from_list(templates, reply_seed_idx)

        if tpl_family_idx == 2:
            echo = _sanitize_echo(content)
            if echo:
                base_reply = f"{echo} {base_reply}".strip()
        elif tpl_family_idx == 3:
            catchphrases = persona_cfg.get("anchor", {}).get("catchphrases") or []
            if catchphrases:
                base_reply = choose_from_list(catchphrases, reply_seed_idx)

        reply = base_reply
        reply = _maybe_add_emote(reply, persona_id, event_id, room_cfg, max_chars)

    reply = strip_mentions(reply)
    reply = sanitize_text(reply)
    reply = truncate(reply, max_chars)
    if not reply:
        reply = "ok"
    return reply
