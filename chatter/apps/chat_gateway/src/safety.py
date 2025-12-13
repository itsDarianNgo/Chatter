import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModerationPattern:
    kind: str
    regex: str
    replacement: str

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.regex)


@dataclass
class ModerationConfig:
    patterns: List[ModerationPattern] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> "ModerationConfig":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        patterns = [
            ModerationPattern(p["kind"], p["regex"], p["replacement"])
            for p in data.get("pii_patterns", [])
        ]
        return cls(patterns)


class SafetyProcessor:
    def __init__(self, max_length: int, moderation_config: Optional[Path]) -> None:
        self.max_length = max_length
        self.moderation = None
        if moderation_config and moderation_config.exists():
            try:
                self.moderation = ModerationConfig.from_file(moderation_config)
                logger.info("Loaded moderation config from %s", moderation_config)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load moderation config %s: %s", moderation_config, exc)
                self.moderation = None
        elif moderation_config:
            logger.warning("Moderation config path %s not found; continuing without redaction", moderation_config)

    def sanitize_content(self, content: str) -> str:
        sanitized = content.replace("\r", " ").replace("\n", " ")
        sanitized = sanitized.strip()
        if len(sanitized) > self.max_length:
            sanitized = sanitized[: self.max_length]
        return sanitized

    def apply_moderation(self, content: str) -> Dict[str, Any]:
        if not self.moderation:
            return {"action": "allow", "reasons": [], "redactions": []}

        redactions: List[Dict[str, Any]] = []
        reasons: List[str] = []
        moderated_content = content
        for pattern in self.moderation.patterns:
            compiled = pattern.compiled()
            if compiled.search(moderated_content):
                reasons.append(pattern.kind)
                moderated_content = compiled.sub(pattern.replacement, moderated_content)
        if reasons:
            return {
                "action": "redact",
                "reasons": reasons,
                "redactions": redactions,
                "content": moderated_content,
            }
        return {"action": "allow", "reasons": [], "redactions": []}

    def process(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        content = message.get("content", "")
        if not isinstance(content, str):
            logger.warning("Dropping message missing content")
            return None
        sanitized = self.sanitize_content(content)
        if not sanitized:
            logger.warning("Dropping message with empty content after sanitization")
            return None

        moderation = self.apply_moderation(sanitized)
        if moderation.get("action") == "redact" and moderation.get("content"):
            sanitized = moderation["content"]
        message["content"] = sanitized
        message["moderation"] = {k: v for k, v in moderation.items() if k != "content"}
        self._apply_trace(message)
        return message

    def _apply_trace(self, message: Dict[str, Any]) -> None:
        trace = message.get("trace")
        if not isinstance(trace, dict):
            trace = {}

        producer = trace.get("producer")
        if not producer:
            trace["producer"] = "unknown"

        processed_by = trace.get("processed_by")
        if isinstance(processed_by, list):
            processed_by = [str(item) for item in processed_by if isinstance(item, (str, bytes))]
        else:
            processed_by = []
        if "chat_gateway" not in processed_by:
            processed_by.append("chat_gateway")
        trace["processed_by"] = processed_by

        trace.setdefault("gateway_ts", datetime.now(timezone.utc).isoformat())
        message["trace"] = trace
