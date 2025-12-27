from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator

from .config_loader import ConfigValidationError


@dataclass(frozen=True)
class AutoCommentaryConfig:
    enabled: bool
    room_id_mode: str
    hype_threshold: float
    trigger_tags: list[str]
    trigger_on_entities: bool
    persona_cooldown_ms: int
    room_rate_limit_ms: int
    max_messages_per_observation: int
    dedupe_window_ms: int
    message_prefix: str
    max_reply_chars: int
    include_obs_id: bool


def _apply_defaults(schema: dict, payload: dict) -> dict:
    defaults_applied = dict(payload)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    for key, prop_schema in properties.items():
        if key in defaults_applied:
            continue
        if isinstance(prop_schema, dict) and "default" in prop_schema:
            defaults_applied[key] = prop_schema["default"]
    return defaults_applied


def _format_validation_error(errors: Iterable[Exception]) -> str:
    for error in errors:
        path = ".".join(str(part) for part in getattr(error, "path", []))
        label = path if path else "$"
        message = getattr(error, "message", str(error))
        return f"{label}: {message}"
    return "unknown validation error"


def _normalize_trigger_tags(tags: Iterable[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        cleaned = str(tag).strip().lower()
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return normalized


def load_auto_commentary_config(
    config_path: Path, schema_path: Path, enabled_override: bool | None = None
) -> AutoCommentaryConfig:
    if not config_path.exists():
        raise ConfigValidationError(f"Auto commentary config not found at {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ConfigValidationError("Auto commentary config must be a JSON object")

    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = _apply_defaults(schema, raw)

    if enabled_override is not None:
        payload["enabled"] = enabled_override

    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if errors:
        raise ConfigValidationError(
            f"Auto commentary config invalid: {_format_validation_error(errors)}"
        )

    trigger_tags = payload.get("trigger_tags") if isinstance(payload.get("trigger_tags"), list) else []
    normalized_tags = _normalize_trigger_tags(trigger_tags)

    return AutoCommentaryConfig(
        enabled=bool(payload["enabled"]),
        room_id_mode=str(payload["room_id_mode"]).lower(),
        hype_threshold=float(payload["hype_threshold"]),
        trigger_tags=normalized_tags,
        trigger_on_entities=bool(payload["trigger_on_entities"]),
        persona_cooldown_ms=int(payload["persona_cooldown_ms"]),
        room_rate_limit_ms=int(payload["room_rate_limit_ms"]),
        max_messages_per_observation=int(payload["max_messages_per_observation"]),
        dedupe_window_ms=int(payload["dedupe_window_ms"]),
        message_prefix=str(payload["message_prefix"]),
        max_reply_chars=int(payload["max_reply_chars"]),
        include_obs_id=bool(payload["include_obs_id"]),
    )
