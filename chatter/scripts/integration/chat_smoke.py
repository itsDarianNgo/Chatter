#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from packages.llm_runtime.src.config_loader import load_llm_provider_config  # noqa: E402
from packages.llm_runtime.src.prompt_renderer import PromptRenderer  # noqa: E402
from packages.llm_runtime.src.types import LLMRequest  # noqa: E402

try:  # Optional local-only dependency
    from packages.llm_runtime.src.litellm_provider import LiteLLMProvider  # type: ignore  # noqa: E402
except Exception as exc:  # noqa: BLE001
    LiteLLMProvider = None  # type: ignore
    IMPORT_ERR = exc
else:
    IMPORT_ERR = None

try:  # Optional for local dev
    from dotenv import load_dotenv  # type: ignore
except Exception:  # noqa: BLE001
    load_dotenv = None  # type: ignore


def _load_local_env_files() -> None:
    """Load .env.local then .env if python-dotenv is available. No-op otherwise."""
    if load_dotenv is None:
        return
    for name in [".env.local", ".env"]:
        p = REPO_ROOT / name
        if p.exists():
            load_dotenv(p, override=False)


def _first_env(*names: str) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v and str(v).strip():
            return str(v).strip()
    return None


def main() -> int:
    _load_local_env_files()

    cfg_path_env = os.getenv("LLM_PROVIDER_CONFIG_PATH", "configs/llm/providers/litellm.example.json")
    cfg_path = Path(cfg_path_env)
    if not cfg_path.is_absolute():
        cfg_path = REPO_ROOT / cfg_path

    if IMPORT_ERR is not None:
        print(f"SKIP: litellm dependency missing ({IMPORT_ERR}), not running chat smoke test")
        return 0

    provider_cfg = load_llm_provider_config(cfg_path)
    if provider_cfg.get("provider") != "litellm":
        print(f"SKIP: provider is not litellm (provider={provider_cfg.get('provider')})")
        return 0

    litellm_cfg: Dict[str, Any] = (
        provider_cfg.get("litellm", {}) if isinstance(provider_cfg.get("litellm"), dict) else {}
    )
    model = str(litellm_cfg.get("model") or "").strip()
    if not model:
        print("SKIP: missing litellm.model in provider config")
        return 0

    # Prefer config’s api_key_env, but allow common fallbacks for local DX.
    api_key_env = str(litellm_cfg.get("api_key_env") or "OPENAI_API_KEY").strip()
    api_key = _first_env(api_key_env, "LITELLM_API_KEY", "OPENAI_API_KEY")
    if not api_key:
        print(f"SKIP: missing {api_key_env} (also tried LITELLM_API_KEY/OPENAI_API_KEY), not running chat smoke test")
        return 0

    used_env = api_key_env if os.getenv(api_key_env) else ("LITELLM_API_KEY" if os.getenv("LITELLM_API_KEY") else "OPENAI_API_KEY")

    renderer = PromptRenderer(REPO_ROOT / "prompts/manifest.json", base_dir=REPO_ROOT)
    req = LLMRequest(
        persona_id="smoke",
        persona_display_name="SmokeTest",
        room_id="room:smoke",
        content="E2E_CHAT_SMOKE please reply with ok",
        marker=None,
        recent_messages=["hello there"],
        tags={"test": "chat_smoke"},
        observation_summary="E2E_CHAT_SMOKE: ping",
        persona_profile="bio: concise helper",
        prompt_id="persona_chat_reply_v2",
    )
    system_prompt, user_prompt = renderer.render_persona_reply(req, prompt_id="persona_chat_reply_v2")
    req.system_prompt = system_prompt
    req.user_prompt = user_prompt

    provider = LiteLLMProvider(provider_cfg)

    try:
        resp = provider.generate(req)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: chat smoke error: {exc}")
        return 1

    text = (resp.text or "").replace("\n", " ").strip()
    if not text:
        print("FAIL: chat smoke returned empty text")
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "model": model,
                "api_key_env_used": used_env,
                "text": text,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
