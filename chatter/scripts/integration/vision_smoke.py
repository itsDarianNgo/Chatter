#!/usr/bin/env python
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from packages.llm_runtime.src.config_loader import load_llm_provider_config  # noqa: E402

try:  # Optional local-only dependency
    from litellm import completion  # type: ignore  # noqa: E402
except Exception as exc:  # noqa: BLE001
    completion = None  # type: ignore[assignment]
    IMPORT_ERR = exc
else:
    IMPORT_ERR = None


def _extract_text(response: Dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        if "content" in message:
            return message["content"] or ""
        if "text" in choices[0]:
            return choices[0]["text"] or ""
    return ""


def _data_url_png(path: Path) -> str:
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def main() -> int:
    cfg_path_env = os.getenv("LLM_PROVIDER_CONFIG_PATH", "configs/llm/providers/litellm.example.json")
    cfg_path = Path(cfg_path_env)
    if not cfg_path.is_absolute():
        cfg_path = REPO_ROOT / cfg_path

    if completion is None:
        print(f"SKIP: litellm dependency missing ({IMPORT_ERR}), not running vision smoke test")
        return 0

    provider_cfg = load_llm_provider_config(cfg_path)
    if provider_cfg.get("provider") != "litellm":
        print(f"SKIP: provider is not litellm (provider={provider_cfg.get('provider')})")
        return 0

    litellm_cfg: Dict[str, Any] = provider_cfg.get("litellm", {}) if isinstance(provider_cfg.get("litellm"), dict) else {}
    model = str(litellm_cfg.get("model") or "").strip()
    if not model:
        print("SKIP: missing litellm.model in provider config")
        return 0

    api_key_env = str(litellm_cfg.get("api_key_env") or "OPENAI_API_KEY").strip()
    api_key = os.getenv(api_key_env)
    if not api_key:
        print(f"SKIP: missing {api_key_env}, not running vision smoke test")
        return 0

    image_path = REPO_ROOT / "fixtures" / "stream" / "frame_fixture_1.png"
    if not image_path.exists():
        print(f"FAIL: missing fixture image: {image_path}")
        return 1

    messages = [
        {"role": "system", "content": "You are a concise helper."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Reply with: ok"},
                {"type": "image_url", "image_url": {"url": _data_url_png(image_path)}},
            ],
        },
    ]

    kwargs: Dict[str, Any] = {}
    if litellm_cfg.get("api_base"):
        kwargs["api_base"] = litellm_cfg["api_base"]
    kwargs["api_key"] = api_key
    if litellm_cfg.get("temperature") is not None:
        kwargs["temperature"] = litellm_cfg["temperature"]
    if litellm_cfg.get("max_tokens") is not None:
        kwargs["max_tokens"] = litellm_cfg["max_tokens"]
    if litellm_cfg.get("timeout_s") is not None:
        kwargs["timeout"] = litellm_cfg["timeout_s"]
    if litellm_cfg.get("num_retries") is not None:
        kwargs["num_retries"] = litellm_cfg["num_retries"]
    if isinstance(litellm_cfg.get("extra"), dict):
        kwargs.update(litellm_cfg["extra"])

    try:
        resp = completion(model=model, messages=messages, **kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: vision smoke error: {exc}")
        return 1

    text = _extract_text(resp if isinstance(resp, dict) else dict(resp)).replace("\n", " ").strip()
    if not text:
        print("FAIL: vision smoke returned empty text")
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "model": model,
                "text": text,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

