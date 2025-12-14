from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict

from packages.llm_runtime.src import (
    LLMRequest,
    PromptRenderer,
    StubLLMProvider,
    load_llm_provider_config,
)

from .settings import settings
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


class DeterministicReplyGenerator:
    def __init__(self, mode: str = "deterministic") -> None:
        self.generation_mode = mode

    def describe(self) -> dict:
        return {
            "generation_mode": self.generation_mode,
            "llm_provider": None,
            "llm_model": None,
            "prompt_manifest_path": None,
            "provider_config_path": None,
        }

    def generate_reply(self, persona_cfg: Dict, room_cfg: dict, event_msg: Dict, state, tags: Dict) -> str:
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


class LLMReplyGenerator:
    def __init__(
        self, base_path: Path, provider_config_path: str, prompt_manifest_path: str, mode: str = "stub"
    ) -> None:
        self.base_path = base_path
        self.provider_config_path = base_path / provider_config_path
        self.prompt_manifest_path = base_path / prompt_manifest_path
        self.generation_mode = mode
        self.provider_config = load_llm_provider_config(self.provider_config_path)
        try:
            self.max_output_chars = int(self.provider_config.get("max_output_chars", 220))
        except Exception:  # noqa: BLE001
            self.max_output_chars = 220
        self.provider = self._build_provider()
        self.renderer = PromptRenderer(self.prompt_manifest_path, base_dir=base_path)

    def describe(self) -> dict:
        provider_type = self.provider_config.get("provider")
        model = None
        if provider_type == "litellm":
            model = self.provider_config.get("litellm", {}).get("model")
        elif provider_type == "stub":
            model = "stub"

        return {
            "generation_mode": self.generation_mode,
            "llm_provider": provider_type,
            "llm_model": model,
            "prompt_manifest_path": str(self.prompt_manifest_path),
            "provider_config_path": str(self.provider_config_path),
        }

    def _build_provider(self):
        provider_type = self.provider_config.get("provider")
        if provider_type == "stub":
            stub_cfg = self.provider_config.get("stub", {})
            fixtures_path = self.base_path / stub_cfg.get("fixtures_path", "")
            return StubLLMProvider(
                fixtures_path=fixtures_path,
                default_response=stub_cfg.get("default_response", "ok"),
                key_strategy=stub_cfg.get("key_strategy", "persona_marker"),
                max_output_chars=self.max_output_chars,
                provider_name="stub",
            )
        if provider_type == "litellm":
            from packages.llm_runtime.src.litellm_provider import LiteLLMProvider

            return LiteLLMProvider(self.provider_config)
        raise ValueError(f"Unsupported provider type: {provider_type}")

    def _recent_messages(self, state, room_id: str, budget_limit: int, budget_window_ms: int):
        room_state = state.get_room_state(room_id, budget_limit, budget_window_ms)
        return [msg.get("content", "") or "" for msg in room_state.recent_messages]

    def generate_reply(self, persona_cfg: Dict, room_cfg: dict, event_msg: Dict, state, tags: Dict) -> str:
        persona_id = persona_cfg.get("persona_id", "persona")
        display_name = persona_cfg.get("display_name", persona_id)
        content = event_msg.get("content", "") or ""
        room_id = event_msg.get("room_id") or room_cfg.get("room_id", "room:demo")
        max_chars = persona_cfg.get("safety", {}).get("max_chars", 200)
        marker = _extract_marker(content)
        timing = room_cfg.get("timing", {})
        budget_limit = int(timing.get("max_bot_msgs_per_10s", settings.room_bot_budget_per_10s_default))
        budget_window_ms = 10_000
        recent = self._recent_messages(state, room_id, budget_limit, budget_window_ms)

        llm_req = LLMRequest(
            persona_id=persona_id,
            persona_display_name=display_name,
            room_id=room_id,
            content=content,
            marker=marker,
            recent_messages=recent,
            tags=tags or {},
        )
        system_prompt, user_prompt = self.renderer.render_persona_reply(llm_req)
        llm_req.system_prompt = system_prompt
        llm_req.user_prompt = user_prompt

        response = self.provider.generate(llm_req)
        reply = response.text
        reply = strip_mentions(reply)
        reply = sanitize_text(reply)
        reply = truncate(reply, min(max_chars, self.max_output_chars))
        if not reply:
            reply = "ok"
        return reply


def build_reply_generator(base_path: Path, mode: str, provider_config_path: str, prompt_manifest_path: str):
    normalized = (mode or "deterministic").lower()
    if normalized in {"stub", "litellm"}:
        return LLMReplyGenerator(base_path, provider_config_path, prompt_manifest_path, mode=normalized)
    return DeterministicReplyGenerator(mode="deterministic")


_default_generator = DeterministicReplyGenerator()


def generate_reply(persona_cfg: Dict, room_cfg: dict, event_msg: Dict, state, tags: Dict) -> str:
    return _default_generator.generate_reply(persona_cfg, room_cfg, event_msg, state, tags)
