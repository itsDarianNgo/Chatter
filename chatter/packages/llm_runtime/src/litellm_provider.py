from __future__ import annotations

import re
from typing import Any, Dict

from litellm import completion

from .provider_base import LLMProvider
from .types import LLMRequest, LLMResponse


def _clean_text(text: str, max_chars: int) -> str:
    single_line = re.sub(r"\s+", " ", text.replace("\n", " ").replace("\r", " ")).strip()
    single_line = single_line.replace("@", "")
    if len(single_line) > max_chars:
        return single_line[: max_chars - 1] + "…" if max_chars > 1 else single_line[:max_chars]
    return single_line


class LiteLLMProvider(LLMProvider):
    def __init__(self, config: Dict[str, Any], provider_name: str = "litellm") -> None:
        self.config = config
        self.provider_name = provider_name
        self.model = config.get("litellm", {}).get("model", "")
        if not self.model:
            raise ValueError("LiteLLMProvider requires litellm.model")
        self.max_output_chars = int(config.get("max_output_chars", 200))

    def _request_kwargs(self) -> Dict[str, Any]:
        litellm_cfg = self.config.get("litellm", {})
        kwargs: Dict[str, Any] = {}
        if litellm_cfg.get("api_base"):
            kwargs["api_base"] = litellm_cfg["api_base"]
        api_key_env = litellm_cfg.get("api_key_env")
        if api_key_env:
            from os import getenv

            api_key = getenv(api_key_env)
            if api_key:
                kwargs["api_key"] = api_key
        if litellm_cfg.get("temperature") is not None:
            kwargs["temperature"] = litellm_cfg["temperature"]
        if litellm_cfg.get("max_tokens") is not None:
            kwargs["max_tokens"] = litellm_cfg["max_tokens"]
        if litellm_cfg.get("timeout_s") is not None:
            kwargs["timeout"] = litellm_cfg["timeout_s"]
        if litellm_cfg.get("num_retries") is not None:
            kwargs["num_retries"] = litellm_cfg["num_retries"]
        if litellm_cfg.get("extra"):
            kwargs.update(litellm_cfg["extra"])
        return kwargs

    def _extract_text(self, response: Dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            if "content" in message:
                return message["content"] or ""
            if "text" in choices[0]:
                return choices[0]["text"] or ""
        return ""

    def generate(self, req: LLMRequest) -> LLMResponse:
        messages = [
            {"role": "system", "content": req.system_prompt or ""},
            {"role": "user", "content": req.user_prompt or req.content},
        ]
        kwargs = self._request_kwargs()
        raw_resp = completion(model=self.model, messages=messages, **kwargs)
        text = _clean_text(self._extract_text(raw_resp), self.max_output_chars)
        meta: Dict[str, Any] = {
            "model": self.model,
            "usage": raw_resp.get("usage"),
        }
        return LLMResponse(text=text or "lol", provider=self.provider_name, model=self.model, meta=meta)
