import json
import logging
from pathlib import Path
from typing import Dict, Iterable

from jsonschema import Draft202012Validator

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    pass


class ConfigLoader:
    def __init__(self, base_path: Path, room_schema_path: Path, persona_schema_path: Path) -> None:
        self.base_path = base_path
        self.room_schema_path = room_schema_path
        self.persona_schema_path = persona_schema_path
        self._room_validator = self._load_validator(room_schema_path)
        self._persona_validator = self._load_validator(persona_schema_path)

    def _load_validator(self, path: Path) -> Draft202012Validator:
        with path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)

    def load_room_config(self, path: str) -> dict:
        config_path = (self.base_path / path).resolve()
        if not config_path.exists():
            raise ConfigValidationError(f"Room config not found at {config_path}")
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self._room_validator.validate(data)
        return data

    def load_persona_configs(self, directory: str, enabled_personas: Iterable[str]) -> Dict[str, dict]:
        personas: Dict[str, dict] = {}
        dir_path = (self.base_path / directory).resolve()
        if not dir_path.exists():
            raise ConfigValidationError(f"Persona config directory not found at {dir_path}")
        enabled_set = set(enabled_personas)
        for persona_file in sorted(dir_path.glob("*.json")):
            with persona_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            try:
                self._persona_validator.validate(data)
            except Exception as exc:  # noqa: BLE001
                raise ConfigValidationError(f"Invalid persona config {persona_file.name}: {exc}") from exc
            persona_id = data.get("persona_id")
            if persona_id in enabled_set:
                personas[persona_id] = data
        if not personas:
            logger.warning("No enabled personas found; service will not publish messages")
        return personas
