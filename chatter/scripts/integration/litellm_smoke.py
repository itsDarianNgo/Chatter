#!/usr/bin/env python
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from packages.llm_runtime.src.config_loader import load_llm_provider_config  # noqa: E402
from packages.llm_runtime.src.litellm_provider import LiteLLMProvider  # noqa: E402
from packages.llm_runtime.src.types import LLMRequest  # noqa: E402


def main() -> int:
    cfg_path_env = os.getenv("LLM_PROVIDER_CONFIG_PATH", "configs/llm/providers/litellm.example.json")
    cfg_path = Path(cfg_path_env)
    if not cfg_path.is_absolute():
        cfg_path = REPO_ROOT / cfg_path

    provider_cfg = load_llm_provider_config(cfg_path)
    litellm_cfg = provider_cfg.get("litellm", {})
    api_env = litellm_cfg.get("api_key_env") or "OPENAI_API_KEY"

    api_key = os.getenv(api_env)
    if not api_key:
        print(f"SKIP: missing {api_env}, not running LiteLLM smoke test")
        return 0

    provider = LiteLLMProvider(provider_cfg)
    req = LLMRequest(
        persona_id="smoke",
        persona_display_name="SmokeTest",
        room_id="room:smoke",
        content="Say 'ok' only.",
        marker=None,
        recent_messages=[],
        tags={},
        system_prompt="You are a concise helper.",
        user_prompt="Reply with: ok",
    )

    try:
        resp = provider.generate(req)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: litellm smoke error: {exc}")
        return 1

    text = (resp.text or "").replace("\n", " ").strip()
    if not text:
        print("FAIL: litellm smoke returned empty text")
        return 1

    print(f"PASS: litellm smoke ok: {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
