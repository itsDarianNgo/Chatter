from __future__ import annotations

import hashlib
import os
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


def _resolve_env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return ""


def _select_api_key_env(existing: str | None, candidates: list[str]) -> str | None:
    for name in candidates:
        value = os.getenv(name)
        if value and value.strip():
            return name
    if existing:
        return str(existing)
    return candidates[0] if candidates else None


def _apply_llm_env_overrides(provider_config: Dict) -> Dict:
    provider_override = _resolve_env_value("LLM_PROVIDER")
    if not provider_override:
        return provider_config

    normalized = provider_override.lower()
    if normalized not in {"stub", "litellm"}:
        raise ValueError(f"Unsupported LLM_PROVIDER override: {provider_override}")

    cfg = dict(provider_config)
    cfg.setdefault("schema_name", "LLMProviderConfig")
    cfg.setdefault("schema_version", "1.0.0")
    cfg.setdefault("timeout_ms", 30000)
    cfg.setdefault("max_output_chars", int(provider_config.get("max_output_chars", 220)))

    if normalized == "litellm":
        litellm_cfg = dict(cfg.get("litellm") or {})
        model = _resolve_env_value("LLM_MODEL", "PERSONA_LLM_MODEL") or str(litellm_cfg.get("model") or "").strip()
        if not model:
            raise ValueError("LLM_MODEL or PERSONA_LLM_MODEL is required for LLM_PROVIDER=litellm")
        litellm_cfg["model"] = model
        api_base = _resolve_env_value("LLM_BASE_URL", "LITELLM_BASE_URL")
        if api_base:
            litellm_cfg["api_base"] = api_base
        api_key_env = _select_api_key_env(litellm_cfg.get("api_key_env"), ["LLM_API_KEY", "OPENAI_API_KEY", "LITELLM_API_KEY"])
        if api_key_env:
            litellm_cfg["api_key_env"] = api_key_env
        cfg["litellm"] = litellm_cfg
        cfg["provider"] = "litellm"
        cfg["mode"] = "litellm_live"
    else:
        cfg["provider"] = "stub"
        cfg["mode"] = "deterministic_stub"

    return cfg


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


def _extract_observation_summary(context: str) -> str:
    if not context:
        return ""
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if idx == 0 and len(lines) > 1:
            if "OBS:" not in line and "|" not in line and "tags=" not in line and "entities=" not in line and "hype=" not in line:
                continue
        candidate = line
        if candidate.lower().startswith("obs:"):
            candidate = candidate[4:].strip()
        parts = [part.strip() for part in candidate.split(" | ") if part.strip()]
        for part in parts:
            lower = part.lower()
            if lower.startswith(("tags=", "entities=", "hype=")):
                continue
            if re.match(r"^\d{4}-\d{2}-\d{2}t", lower):
                continue
            return part
    return ""


def _build_persona_profile(persona_cfg: Dict) -> str:
    lines: list[str] = []
    anchor = persona_cfg.get("anchor") if isinstance(persona_cfg, dict) else None
    if isinstance(anchor, dict):
        bio = anchor.get("bio")
        if isinstance(bio, str) and bio.strip():
            lines.append(f"bio: {sanitize_text(bio)}")

        voice_rules = anchor.get("voice_rules") if isinstance(anchor.get("voice_rules"), dict) else {}
        if isinstance(voice_rules, dict):
            for key in ("style", "caps_style", "punctuation", "emoji_density"):
                value = voice_rules.get(key)
                if isinstance(value, str) and value.strip():
                    lines.append(f"{key}: {sanitize_text(value)}")

            for key in ("emote_habits", "catchphrase_seeds", "banned_topics"):
                items = voice_rules.get(key) if isinstance(voice_rules.get(key), list) else []
                cleaned = [sanitize_text(str(item)) for item in items if str(item).strip()]
                if cleaned:
                    lines.append(f"{key}: {', '.join(cleaned)}")

        catchphrases = anchor.get("catchphrases") if isinstance(anchor.get("catchphrases"), list) else []
        cleaned_phrases = [sanitize_text(str(item)) for item in catchphrases if str(item).strip()]
        if cleaned_phrases:
            lines.append(f"catchphrases: {', '.join(cleaned_phrases)}")

    return "\n".join(lines)


def format_auto_commentary_reply(
    base_reply: str,
    observation_summary: str,
    observation_context: str,
    message_prefix: str,
    include_obs_id: bool,
    observation_id: str | None,
    max_chars: int,
) -> str:
    if max_chars <= 0:
        return ""
    prefix = sanitize_text(message_prefix or "")
    summary = sanitize_text(observation_summary or "")
    obs_id_segment = f"[{observation_id}]" if include_obs_id and observation_id else ""
    base_reply = sanitize_text(base_reply or "")
    core = base_reply or summary
    if not core:
        fallback = _extract_observation_summary(observation_context)
        core = sanitize_text(fallback) if fallback else ""

    core_parts = [part for part in (prefix, obs_id_segment, core) if part]
    combined = " ".join(core_parts)

    combined = strip_mentions(combined)
    combined = sanitize_text(combined)
    combined = truncate(combined, max_chars)
    if not combined:
        combined = truncate(prefix or "ok", max_chars)
    return combined


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

    def generate_reply(
        self,
        persona_cfg: Dict,
        room_cfg: dict,
        event_msg: Dict,
        state,
        tags: Dict,
        memory_context: str | None = None,
        observation_context: str | None = None,
        observation_summary: str | None = None,
        prompt_id: str | None = None,
        prompt_purpose: str | None = None,
    ) -> str:
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
        (
            self.provider,
            self.provider_config,
            self.max_output_chars,
        ) = build_llm_provider(self.base_path, self.provider_config_path)
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

    def _recent_messages(self, state, room_id: str, budget_limit: int, budget_window_ms: int):
        room_state = state.get_room_state(room_id, budget_limit, budget_window_ms)
        return [msg.get("content", "") or "" for msg in room_state.recent_messages]

    def generate_reply(
        self,
        persona_cfg: Dict,
        room_cfg: dict,
        event_msg: Dict,
        state,
        tags: Dict,
        memory_context: str | None = None,
        observation_context: str | None = None,
        observation_summary: str | None = None,
        prompt_id: str | None = None,
        prompt_purpose: str | None = None,
    ) -> str:
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
        persona_profile = _build_persona_profile(persona_cfg)
        obs_summary = observation_summary or _extract_observation_summary(observation_context or "")

        llm_req = LLMRequest(
            persona_id=persona_id,
            persona_display_name=display_name,
            room_id=room_id,
            content=content,
            marker=marker,
            recent_messages=recent,
            tags=tags or {},
            memory_context=memory_context or "",
            observation_context=observation_context or "",
            observation_summary=obs_summary,
            persona_profile=persona_profile,
            prompt_id=prompt_id,
        )
        if (prompt_purpose or "persona_reply") == "persona_auto_commentary":
            system_prompt, user_prompt = self.renderer.render_persona_auto_commentary(llm_req, prompt_id=prompt_id)
        else:
            system_prompt, user_prompt = self.renderer.render_persona_reply(llm_req, prompt_id=prompt_id)
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

    def render_memory_extract_prompts(self, req: LLMRequest):
        return self.renderer.render_memory_extract(req)


def build_reply_generator(base_path: Path, mode: str, provider_config_path: str, prompt_manifest_path: str):
    normalized = (mode or "deterministic").lower()
    if normalized in {"stub", "litellm"}:
        return LLMReplyGenerator(base_path, provider_config_path, prompt_manifest_path, mode=normalized)
    return DeterministicReplyGenerator(mode="deterministic")


_default_generator = DeterministicReplyGenerator()


def generate_reply(
    persona_cfg: Dict,
    room_cfg: dict,
    event_msg: Dict,
    state,
    tags: Dict,
    memory_context: str | None = None,
    observation_context: str | None = None,
    observation_summary: str | None = None,
    prompt_id: str | None = None,
    prompt_purpose: str | None = None,
) -> str:
    return _default_generator.generate_reply(
        persona_cfg,
        room_cfg,
        event_msg,
        state,
        tags,
        memory_context,
        observation_context,
        observation_summary,
        prompt_id,
        prompt_purpose,
    )


def build_llm_provider(base_path: Path, provider_config_path: Path):
    provider_config = load_llm_provider_config(provider_config_path)
    provider_config = _apply_llm_env_overrides(provider_config)
    try:
        max_output_chars = int(provider_config.get("max_output_chars", 220))
    except Exception:  # noqa: BLE001
        max_output_chars = 220

    provider_type = provider_config.get("provider")
    if provider_type == "stub":
        stub_cfg = provider_config.get("stub", {})
        fixtures_path = base_path / stub_cfg.get("fixtures_path", "")
        provider = StubLLMProvider(
            fixtures_path=fixtures_path,
            default_response=stub_cfg.get("default_response", "ok"),
            key_strategy=stub_cfg.get("key_strategy", "persona_marker"),
            max_output_chars=max_output_chars,
            provider_name="stub",
        )
    elif provider_type == "litellm":
        from packages.llm_runtime.src.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(provider_config)
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")

    return provider, provider_config, max_output_chars
