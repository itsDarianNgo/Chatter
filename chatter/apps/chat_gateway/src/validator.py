import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator


class ChatMessageValidator:
    def __init__(self, schema_path: Path) -> None:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        Draft202012Validator.check_schema(schema)
        self.validator = Draft202012Validator(schema)

    def validate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validator.validate(payload)
        return payload
