from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LLMRequest:
    persona_id: str
    persona_display_name: str
    room_id: str
    content: str
    marker: Optional[str] = None
    recent_messages: List[str] = field(default_factory=list)
    tags: Dict[str, object] = field(default_factory=dict)
    memory_context: str = ""
    observation_context: str = ""
    system_prompt: str = ""
    user_prompt: str = ""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: Optional[str] = None
    meta: Dict[str, object] = field(default_factory=dict)
