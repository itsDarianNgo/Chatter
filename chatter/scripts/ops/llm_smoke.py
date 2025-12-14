#!/usr/bin/env python
from __future__ import annotations

import os
from pathlib import Path

from packages.llm_runtime.src.config_loader import load_llm_provider_config
from packages.llm_runtime.src.litellm_provider import LiteLLMProvider
from packages.llm_runtime.src.types import LLMRequest


def main() -> int:
    cfg_path = Path("configs/llm/providers/litellm.example.json")
    provider_cfg = load_llm_provider_config(cfg_path)
    litellm_cfg = provider_cfg.get("litellm", {})
    api_env = litellm_cfg.get("api_key_env") or "OPENAI_API_KEY"
    if not os.getenv(api_env):
        print(f"SKIP: missing API key env {api_env}")
        return 0

    provider = LiteLLMProvider(provider_cfg)
    req = LLMRequest(
        persona_id="smoke",
        persona_display_name="SmokeTest",
        room_id="room:smoke",
        content="Provide a short greeting",
        marker=None,
        recent_messages=[],
        tags={},
        system_prompt="You are a concise helper.",
        user_prompt="Say hello in one short line.",
    )
    resp = provider.generate(req)
    print(f"Provider: {resp.provider} Model: {resp.model} Text: {resp.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
