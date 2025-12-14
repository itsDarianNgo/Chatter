from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

from .hash_utils import canonical_prompt_text
from .prompt_loader import load_prompt_manifest, verify_prompt_files, verify_sha256
from .types import LLMRequest


class PromptRenderer:
    """Render prompts using the manifest for persona replies.

    Ensures prompt files exist and match recorded digests before rendering.
    """

    def __init__(self, manifest_path: Path, base_dir: Path | None = None) -> None:
        self.manifest_path = manifest_path
        self.base_dir = base_dir or manifest_path.parents[1]
        self.manifest = load_prompt_manifest(manifest_path)
        verify_prompt_files(self.manifest, self.base_dir)
        verify_sha256(self.manifest, self.base_dir)
        self.persona_prompt = self._load_prompt_text("persona_reply")

    def _load_prompt_text(self, purpose: str) -> str:
        for prompt in self.manifest.get("prompts", []):
            if prompt.get("purpose") == purpose:
                prompt_path = self.base_dir / prompt["path"]
                return canonical_prompt_text(prompt_path)
        raise ValueError(f"No prompt found for purpose={purpose}")

    def _format_recent(self, recent_messages: List[str] | None) -> str:
        lines: List[str] = []
        for msg in (recent_messages or [])[-5:]:
            safe = str(msg).replace("\n", " ").replace("\r", " ").strip()
            if safe:
                lines.append(f"- {safe}")
        return "\n".join(lines) if lines else "(none)"

    def render_persona_reply(self, req: LLMRequest) -> Tuple[str, str]:
        recent_block = self._format_recent(req.recent_messages)
        policy_tags = json.dumps(req.tags or {}, sort_keys=True)
        user_prompt = (
            f"persona: {req.persona_display_name}\n"
            f"room: {req.room_id}\n"
            f"policy_tags: {policy_tags}\n"
            "--- BEGIN CHAT CONTEXT ---\n"
            f"recent_messages:\n{recent_block}\n"
            f"triggering_message: {req.content}\n"
            "--- END CHAT CONTEXT ---"
        )
        return self.persona_prompt, user_prompt
