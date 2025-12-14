from __future__ import annotations

from typing import Protocol

from .types import LLMRequest, LLMResponse


class LLMProvider(Protocol):
    def generate(self, req: LLMRequest) -> LLMResponse:  # pragma: no cover - protocol
        ...
