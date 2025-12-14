from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from packages.llm_runtime.src import LLMProvider, LLMRequest, PromptRenderer

from .policy import should_store_item
from .redaction import apply_redactions
from .types import MemoryItem
from .validate import validate_memory_item_dict


@dataclass
class LLMMemoryExtractResult:
    accepted_items: List[MemoryItem] = field(default_factory=list)
    rejected_count: int = 0
    redacted_count: int = 0
    raw_text: str = ""
    error: str | None = None
    provider: str | None = None
    model: str | None = None


class LLMMemoryExtractor:
    def __init__(
        self,
        provider: LLMProvider,
        renderer: PromptRenderer,
        policy: Dict[str, Any],
        *,
        max_items: int = 5,
        max_chars: int = 800,
        scope_user_enabled: bool = False,
    ) -> None:
        self.provider = provider
        self.renderer = renderer
        self.policy = policy or {}
        self.max_items = max_items
        self.max_chars = max_chars
        self.scope_user_enabled = scope_user_enabled

    @staticmethod
    def _now_ts() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _derive_scope(self, room_id: str, persona_id: str | None, user_id: str | None) -> Tuple[str, str]:
        scopes = self.policy.get("scopes") or []
        scope = "persona_room"
        if self.scope_user_enabled and user_id and "persona_user" in scopes:
            scope = "persona_user"
        elif "persona_room" not in scopes and "persona" in scopes:
            scope = "persona"
        elif "persona_room" in scopes:
            scope = "persona_room"
        elif "persona" in scopes:
            scope = "persona"
        elif "persona_user" in scopes and user_id:
            scope = "persona_user"

        safe_persona = persona_id or "persona"
        safe_room = room_id or "room"
        safe_user = user_id or "user"

        if scope == "persona_user":
            scope_key = f"{safe_room}:{safe_persona}:{safe_user}"
        elif scope == "persona":
            scope_key = safe_persona
        else:
            scope_key = f"{safe_room}:{safe_persona}"

        scope_key = scope_key.replace("\n", " ").replace("\r", " ").strip()
        if not scope_key:
            scope_key = f"{safe_room}:{safe_persona}"
        return scope, scope_key

    def _extract_json_candidates(self, text: str) -> Tuple[List[Dict], str | None]:
        stripped = text.strip()
        if not stripped:
            return [], "empty_output"

        def _parse(candidate: str) -> Tuple[List[Dict], str | None]:
            try:
                parsed = json.loads(candidate)
            except Exception:
                return [], "json_parse_failed"

            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)], None
            if isinstance(parsed, dict):
                if isinstance(parsed.get("items"), list):
                    return [item for item in parsed.get("items", []) if isinstance(item, dict)], None
                return [parsed], None
            return [], "unexpected_shape"

        candidates, err = _parse(stripped)
        if candidates:
            return candidates, None

        first_bracket = stripped.find("[")
        last_bracket = stripped.rfind("]")
        if 0 <= first_bracket < last_bracket:
            candidates, err = _parse(stripped[first_bracket : last_bracket + 1])
            if candidates:
                return candidates, None

        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if 0 <= first_brace < last_brace:
            candidates, err = _parse(stripped[first_brace : last_brace + 1])
            if candidates:
                return candidates, None

        return [], err

    def _normalize_candidate(
        self,
        candidate: Dict[str, Any],
        *,
        room_id: str,
        persona_id: str | None,
        user_id: str | None,
        display_name: str | None,
        message_id: str | None,
        origin: str | None,
    ) -> Dict[str, Any]:
        normalized = dict(candidate)
        normalized.setdefault("schema_name", "MemoryItem")
        normalized.setdefault("schema_version", "1.0.0")
        normalized.setdefault("ts", self._now_ts())
        try:
            datetime.fromisoformat(str(normalized.get("ts")).replace("Z", "+00:00"))
        except Exception:
            normalized["ts"] = self._now_ts()
        normalized.setdefault("subject", persona_id or display_name or "room")
        normalized.setdefault("category", "room_lore")
        try:
            confidence_val = float(normalized.get("confidence", 0.5))
        except Exception:
            confidence_val = 0.0
        normalized["confidence"] = max(0.0, min(1.0, confidence_val))

        ttl_default = self.policy.get("ttl_days_default")
        ttl_val = normalized.get("ttl_days")
        if ttl_val is None and ttl_default is not None:
            normalized["ttl_days"] = ttl_default
        else:
            try:
                normalized["ttl_days"] = int(ttl_val)
            except Exception:
                if ttl_default is not None:
                    normalized["ttl_days"] = ttl_default

        value = normalized.get("value")
        if isinstance(value, str):
            normalized["value"] = value.strip()[:256]
        elif value is None:
            normalized["value"] = ""
        else:
            normalized["value"] = str(value)[:256]

        scope = normalized.get("scope")
        scope_key = normalized.get("scope_key")
        if not scope or not scope_key:
            scope, scope_key = self._derive_scope(room_id, persona_id, user_id)
            normalized["scope"] = scope
            normalized["scope_key"] = scope_key
        else:
            normalized["scope_key"] = str(scope_key).replace("\n", " ").replace("\r", " ").strip()

        source = normalized.get("source")
        if not isinstance(source, dict):
            source = {}
        source.setdefault("kind", "chat_message")
        source.setdefault("message_id", message_id)
        source.setdefault("user_id", user_id)
        source.setdefault("origin", (origin or "human"))
        normalized["source"] = source

        if not normalized.get("id"):
            seed = f"{room_id}:{persona_id}:{normalized.get('value')}:{normalized.get('ts')}"
            normalized["id"] = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

        return normalized

    def extract(
        self,
        *,
        content: str,
        room_id: str,
        persona_id: str | None,
        user_id: str | None,
        display_name: str | None,
        message_id: str | None,
        origin: str | None = "human",
        recent_messages: List[str] | None = None,
        marker: str | None = None,
    ) -> LLMMemoryExtractResult:
        result = LLMMemoryExtractResult()

        llm_req = LLMRequest(
            persona_id=persona_id or "memory",
            persona_display_name=display_name or persona_id or "memory",
            room_id=room_id,
            content=content,
            marker=marker or "E2E_TEST_MEMORY_LLM",
            recent_messages=recent_messages or [],
            tags={},
        )
        system_prompt, user_prompt = self.renderer.render_memory_extract(llm_req)
        llm_req.system_prompt = system_prompt
        llm_req.user_prompt = user_prompt

        try:
            response = self.provider.generate(llm_req)
            result.raw_text = (response.text or "")[: self.max_chars]
            result.provider = getattr(response, "provider", None)
            result.model = getattr(response, "model", None)
        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)
            return result

        candidates, parse_err = self._extract_json_candidates(result.raw_text)
        if parse_err:
            result.error = parse_err
            return result

        for candidate in candidates[: self.max_items]:
            if not isinstance(candidate, dict):
                result.rejected_count += 1
                continue

            normalized = self._normalize_candidate(
                candidate,
                room_id=room_id,
                persona_id=persona_id,
                user_id=user_id,
                display_name=display_name,
                message_id=message_id,
                origin=origin,
            )

            redacted_value, notes = apply_redactions(normalized.get("value", ""), self.policy)
            normalized["value"] = redacted_value
            if notes:
                normalized["redactions"] = list(notes)
                result.redacted_count += 1
            if not redacted_value or redacted_value.replace("[REDACTED]", "").strip() == "":
                result.rejected_count += 1
                continue

            try:
                validate_memory_item_dict(normalized)
            except Exception as exc:  # noqa: BLE001
                result.rejected_count += 1
                result.error = str(exc)
                continue

            allowed, reason = should_store_item(self.policy, normalized)
            if not allowed:
                result.rejected_count += 1
                result.error = reason
                continue

            try:
                memory_item = MemoryItem.from_dict(normalized)
                result.accepted_items.append(memory_item)
            except Exception as exc:  # noqa: BLE001
                result.rejected_count += 1
                result.error = str(exc)
                continue

        if not result.accepted_items and result.error is None:
            result.error = "no_items_accepted"

        return result


__all__ = ["LLMMemoryExtractor", "LLMMemoryExtractResult"]
