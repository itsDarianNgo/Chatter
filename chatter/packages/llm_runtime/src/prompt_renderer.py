from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

from .hash_utils import canonical_prompt_text
from .prompt_loader import load_prompt_manifest, verify_prompt_files, verify_sha256
from .types import LLMRequest


class PromptRenderer:
    """Render prompts using the manifest.

    Ensures prompt files exist and match recorded digests before rendering.
    """

    def __init__(self, manifest_path: Path, base_dir: Path | None = None) -> None:
        self.manifest_path = manifest_path
        self.base_dir = base_dir or manifest_path.parents[1]
        self.manifest = load_prompt_manifest(manifest_path)
        verify_prompt_files(self.manifest, self.base_dir)
        verify_sha256(self.manifest, self.base_dir)
        self.prompt_by_id = {}
        self.prompt_by_purpose = {}
        for prompt in self.manifest.get("prompts", []):
            prompt_id = prompt.get("id")
            prompt_purpose = prompt.get("purpose")
            prompt_path = self.base_dir / prompt["path"]
            if prompt_id:
                self.prompt_by_id[str(prompt_id)] = canonical_prompt_text(prompt_path)
            if prompt_purpose and prompt_purpose not in self.prompt_by_purpose:
                self.prompt_by_purpose[str(prompt_purpose)] = str(prompt_id)

        self.memory_extract_prompt = self._resolve_prompt_text("memory_extract", None)
        self.stream_observation_prompt = self._resolve_prompt_text("stream_observation", None)

    def _resolve_prompt_text(self, purpose: str, prompt_id: str | None) -> str:
        if prompt_id:
            text = self.prompt_by_id.get(prompt_id)
            if text is not None:
                return text
            raise ValueError(f"No prompt found for id={prompt_id}")

        default_id = self.prompt_by_purpose.get(purpose)
        if default_id:
            return self.prompt_by_id[default_id]
        raise ValueError(f"No prompt found for purpose={purpose}")

    def _format_recent(self, recent_messages: List[str] | None) -> str:
        lines: List[str] = []
        for msg in (recent_messages or [])[-5:]:
            safe = str(msg).replace("\n", " ").replace("\r", " ").strip()
            if safe:
                lines.append(f"- {safe}")
        return "\n".join(lines) if lines else "(none)"

    def render_persona_reply(self, req: LLMRequest, prompt_id: str | None = None) -> Tuple[str, str]:
        recent_block = self._format_recent(req.recent_messages)
        policy_tags = json.dumps(req.tags or {}, sort_keys=True)
        memory_block = req.memory_context or "None"
        observation_block = req.observation_context or "None"
        observation_summary = req.observation_summary or "None"
        persona_profile = req.persona_profile or "None"
        user_prompt = (
            f"persona: {req.persona_display_name}\n"
            f"room: {req.room_id}\n"
            f"policy_tags: {policy_tags}\n"
            "PERSONA_PROFILE:\n"
            f"{persona_profile}\n"
            "TRIGGER_MESSAGE:\n"
            f"{req.content}\n"
            "RECENT_CHAT:\n"
            f"{recent_block}\n"
            "OBSERVATION_SUMMARY:\n"
            f"{observation_summary}\n"
            "STREAM_OBSERVATIONS:\n"
            f"{observation_block}\n"
            "MEMORY_CONTEXT:\n"
            f"{memory_block}"
        )
        system_prompt = self._resolve_prompt_text("persona_reply", prompt_id)
        return system_prompt, user_prompt

    def render_persona_auto_commentary(
        self, req: LLMRequest, prompt_id: str | None = None
    ) -> Tuple[str, str]:
        recent_block = self._format_recent(req.recent_messages)
        observation_block = req.observation_context or "None"
        observation_summary = req.observation_summary or "None"
        persona_profile = req.persona_profile or "None"
        user_prompt = (
            f"persona: {req.persona_display_name}\n"
            f"room: {req.room_id}\n"
            "PERSONA_PROFILE:\n"
            f"{persona_profile}\n"
            "OBSERVATION_SUMMARY:\n"
            f"{observation_summary}\n"
            "STREAM_OBSERVATIONS:\n"
            f"{observation_block}\n"
            "RECENT_CHAT:\n"
            f"{recent_block}"
        )
        system_prompt = self._resolve_prompt_text("persona_auto_commentary", prompt_id)
        return system_prompt, user_prompt

    def render_memory_extract(self, req: LLMRequest) -> Tuple[str, str]:
        recent_block = self._format_recent(req.recent_messages)
        payload = {
            "room_id": req.room_id,
            "persona_id": req.persona_id,
            "persona_name": req.persona_display_name,
            "message": req.content,
            "recent_messages": req.recent_messages or [],
        }
        user_prompt = (
            "MEMORY EXTRACTION REQUEST\n"
            f"RECENT_CHAT:\n{recent_block}\n"
            f"TRIGGER_MESSAGE:\n{req.content}\n"
            f"PAYLOAD_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        return self.memory_extract_prompt, user_prompt

    def render_stream_observation(self, payload: dict) -> Tuple[str, str]:
        user_prompt = (
            "STREAM OBSERVATION REQUEST\n"
            f"PAYLOAD_JSON:\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )
        return self.stream_observation_prompt, user_prompt
