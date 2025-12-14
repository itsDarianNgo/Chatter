from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict

from .provider_base import LLMProvider
from .types import LLMRequest, LLMResponse


def _load_fixtures(path: Path) -> Dict[str, str]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return {case["key"]: case["response"] for case in payload.get("cases", [])}


def _clean_text(text: str, max_chars: int) -> str:
    single_line = re.sub(r"\s+", " ", text.replace("\n", " ").replace("\r", " ")).strip()
    single_line = single_line.replace("@", "")
    if len(single_line) > max_chars:
        return single_line[: max_chars - 1] + "…"
    return single_line


def _marker_prefix(marker: str) -> str:
    tokens = ["E2E_TEST_BOTLOOP_", "E2E_TEST_POLICY_", "E2E_TEST_", "E2E_MARKER_"]
    for token in tokens:
        if token in marker:
            idx = marker.find(token)
            return marker[idx : idx + len(token) + 12]
    return marker[:16]


def _is_memory_extract(req: LLMRequest) -> bool:
    haystack = "\n".join([req.system_prompt or "", req.user_prompt or ""])
    return "MEMORY EXTRACTION REQUEST" in haystack


def _build_memory_extract_response(req: LLMRequest) -> str:
    content = req.content or ""
    match = re.search(r"streamer is called\s+([A-Za-z0-9_()\-]+)", content, flags=re.IGNORECASE)
    value = match.group(1) if match else "Captain"
    item = {
        "schema_name": "MemoryItem",
        "schema_version": "1.0.0",
        "id": "memory_stub_streamer",
        "ts": "2024-01-01T00:00:00Z",
        "category": "room_lore",
        "subject": "streamer_name",
        "value": value,
        "confidence": 0.9,
        "ttl_days": 14,
        "source": {"kind": "chat_message", "message_id": None, "user_id": None, "origin": "human"},
    }
    return json.dumps([item], ensure_ascii=False)


class StubLLMProvider(LLMProvider):
    def __init__(
        self,
        fixtures_path: Path,
        default_response: str,
        key_strategy: str = "persona_marker",
        max_output_chars: int = 200,
        provider_name: str = "stub",
    ) -> None:
        self.fixtures_path = fixtures_path
        self.default_response = default_response
        self.key_strategy = key_strategy
        self.max_output_chars = max_output_chars
        self.provider_name = provider_name
        self.fixtures = _load_fixtures(fixtures_path)

    def _persona_marker_key(self, req: LLMRequest) -> str:
        prefix = _marker_prefix(req.marker) if req.marker else ""
        base_key = f"{req.persona_id}::{prefix}" if prefix else f"{req.persona_id}::DEFAULT"
        if prefix and base_key in self.fixtures:
            return base_key
        if prefix:
            candidate = f"{req.persona_id}::E2E_TEST_"
            if candidate in self.fixtures and prefix.startswith("E2E_TEST_"):
                return candidate
        return f"{req.persona_id}::DEFAULT"

    def _marker_only_key(self, req: LLMRequest) -> str:
        prefix = _marker_prefix(req.marker) if req.marker else ""
        return prefix or "DEFAULT"

    def _resolve_key(self, req: LLMRequest) -> str:
        if self.key_strategy == "marker_only":
            return self._marker_only_key(req)
        return self._persona_marker_key(req)

    def _lookup_response(self, key: str) -> str:
        if key in self.fixtures:
            return self.fixtures[key]
        return self.default_response

    def generate(self, req: LLMRequest) -> LLMResponse:
        if _is_memory_extract(req):
            text = _build_memory_extract_response(req)
            text = _clean_text(text, self.max_output_chars)
            return LLMResponse(text=text, provider=self.provider_name, model="stub", meta={"mode": "memory_extract"})

        key = self._resolve_key(req)
        raw = self._lookup_response(key)
        text = _clean_text(raw, self.max_output_chars)
        return LLMResponse(text=text, provider=self.provider_name, model=None, meta={"key": key})
