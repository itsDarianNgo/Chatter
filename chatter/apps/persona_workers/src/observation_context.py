from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from jsonschema import Draft202012Validator

from .config_loader import ConfigValidationError
from .state import ObservationEntry
from .text_utils import sanitize_text


@dataclass(frozen=True)
class ObservationContextConfig:
    max_items: int
    max_age_ms: int
    max_chars: int
    include_tags: bool
    include_entities: bool
    include_hype: bool
    include_ts: bool
    format_version: str
    prefix: str
    header: str
    line_template: str
    truncate_suffix: str


@dataclass(frozen=True)
class ObservationContextResult:
    context_text: str
    included_observation_ids: list[str]
    chars_included: int


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


def _validate_line_template(template: str) -> None:
    sample_values = {
        "prefix": "OBS:",
        "ts": "2024-01-01T00:00:00Z | ",
        "summary": "summary",
        "tags": " | tags=demo",
        "entities": " | entities=demo",
        "hype": " | hype=0.0",
    }
    try:
        template.format(**sample_values)
    except KeyError as exc:  # noqa: BLE001
        missing = exc.args[0] if exc.args else "unknown"
        raise ConfigValidationError(f"Invalid observation_context line_template: missing {missing}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ConfigValidationError(f"Invalid observation_context line_template: {exc}") from exc


def load_observation_context_config(
    config_path: Path, schema_path: Path
) -> ObservationContextConfig:
    if not config_path.exists():
        raise ConfigValidationError(f"Observation context config not found at {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ConfigValidationError("Observation context config must be a JSON object")

    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = _apply_defaults(schema, raw)

    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if errors:
        raise ConfigValidationError(
            f"Observation context config invalid: {_format_validation_error(errors)}"
        )

    config = ObservationContextConfig(
        max_items=int(payload["max_items"]),
        max_age_ms=int(payload["max_age_ms"]),
        max_chars=int(payload["max_chars"]),
        include_tags=bool(payload["include_tags"]),
        include_entities=bool(payload["include_entities"]),
        include_hype=bool(payload["include_hype"]),
        include_ts=bool(payload["include_ts"]),
        format_version=str(payload["format_version"]),
        prefix=str(payload["prefix"]),
        header=str(payload["header"]),
        line_template=str(payload["line_template"]),
        truncate_suffix=str(payload["truncate_suffix"]),
    )

    if config.format_version != "v1":
        raise ConfigValidationError(f"Unsupported observation_context format_version: {config.format_version}")

    _validate_line_template(config.line_template)
    return config


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:  # noqa: BLE001
        return None


def _redis_id_ms(redis_id: str) -> int | None:
    if not redis_id:
        return None
    try:
        return int(redis_id.split("-", 1)[0])
    except Exception:  # noqa: BLE001
        return None


def derive_observation_ts_ms(observation: dict, redis_id: str, fallback_ms: int | None = None) -> int:
    obs_ts = observation.get("ts") if isinstance(observation, dict) else None
    if isinstance(obs_ts, str):
        parsed = _parse_ts(obs_ts)
        if parsed is not None:
            return int(parsed.timestamp() * 1000)
    redis_ms = _redis_id_ms(redis_id)
    if redis_ms is not None:
        return redis_ms
    if fallback_ms is not None:
        return fallback_ms
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _entry_ts_ms(entry: ObservationEntry) -> int:
    observation = entry.observation if isinstance(entry.observation, dict) else {}
    return derive_observation_ts_ms(observation, entry.redis_id, entry.ts_ms)


def _entry_ts_label(entry: ObservationEntry) -> str:
    obs_ts = entry.observation.get("ts") if isinstance(entry.observation, dict) else None
    if isinstance(obs_ts, str) and obs_ts.strip():
        return obs_ts.strip()
    redis_ms = _redis_id_ms(entry.redis_id)
    if redis_ms is not None:
        return datetime.fromtimestamp(redis_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    ts_ms = entry.ts_ms
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _format_line(entry: ObservationEntry, config: ObservationContextConfig) -> str:
    observation = entry.observation if isinstance(entry.observation, dict) else {}
    summary_raw = observation.get("summary", "") or ""
    summary = sanitize_text(str(summary_raw)) if summary_raw else ""
    if not summary:
        summary = "(no transcript)"

    prefix_segment = f"{config.prefix} " if config.prefix else ""
    ts_segment = ""
    if config.include_ts:
        ts_label = _entry_ts_label(entry)
        if ts_label:
            ts_segment = f"{ts_label} | "

    tags_segment = ""
    if config.include_tags:
        tags = observation.get("tags") if isinstance(observation.get("tags"), list) else []
        tags_clean = [sanitize_text(str(tag)) for tag in tags if str(tag).strip()]
        if tags_clean:
            tags_segment = f" | tags={','.join(tags_clean)}"

    entities_segment = ""
    if config.include_entities:
        entities = observation.get("entities") if isinstance(observation.get("entities"), list) else []
        entities_clean = [sanitize_text(str(ent)) for ent in entities if str(ent).strip()]
        if entities_clean:
            entities_segment = f" | entities={','.join(entities_clean)}"

    hype_segment = ""
    if config.include_hype:
        hype_value = observation.get("hype_level")
        if isinstance(hype_value, (int, float)):
            hype_segment = f" | hype={float(hype_value):.2f}"

    return config.line_template.format(
        prefix=prefix_segment,
        ts=ts_segment,
        summary=summary,
        tags=tags_segment,
        entities=entities_segment,
        hype=hype_segment,
    ).strip()


def _truncate_text(text: str, max_chars: int, suffix: str) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if not suffix:
        return text[:max_chars]
    if max_chars <= len(suffix):
        return suffix[:max_chars]
    return text[: max_chars - len(suffix)] + suffix


def format_observation_context(
    entries: Sequence[ObservationEntry],
    room_id: str,
    reference_ts_ms: int,
    config: ObservationContextConfig,
) -> ObservationContextResult:
    if not entries or config.max_items <= 0 or config.max_chars <= 0:
        return ObservationContextResult("", [], 0)

    filtered: list[tuple[int, ObservationEntry]] = []
    for entry in entries:
        observation = entry.observation if isinstance(entry.observation, dict) else {}
        if observation.get("room_id") != room_id:
            continue
        ts_ms = _entry_ts_ms(entry)
        if config.max_age_ms >= 0 and reference_ts_ms - ts_ms > config.max_age_ms:
            continue
        filtered.append((ts_ms, entry))

    if not filtered:
        return ObservationContextResult("", [], 0)

    def sort_key(item: tuple[int, ObservationEntry]) -> tuple[int, str]:
        ts_ms, entry = item
        obs_id = ""
        observation = entry.observation if isinstance(entry.observation, dict) else {}
        obs_id = str(observation.get("id") or entry.redis_id)
        return (-ts_ms, obs_id)

    filtered.sort(key=sort_key)
    limited = filtered[: config.max_items] if config.max_items > 0 else filtered

    lines: list[str] = []
    ids: list[str] = []
    for _, entry in limited:
        observation = entry.observation if isinstance(entry.observation, dict) else {}
        obs_id = str(observation.get("id") or entry.redis_id)
        ids.append(obs_id)
        lines.append(_format_line(entry, config))

    if not lines:
        return ObservationContextResult("", [], 0)

    header = config.header or ""
    if header:
        block = f"{header}\n" + "\n".join(lines)
    else:
        block = "\n".join(lines)

    truncated = _truncate_text(block, config.max_chars, config.truncate_suffix)
    return ObservationContextResult(truncated, ids, len(truncated))
