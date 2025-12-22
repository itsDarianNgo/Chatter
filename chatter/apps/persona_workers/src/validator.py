import json
from pathlib import Path

from jsonschema import Draft202012Validator


class JSONSchemaValidator:
    def __init__(self, schema_path: Path) -> None:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        Draft202012Validator.check_schema(schema)
        self.validator = Draft202012Validator(schema)

    def validate(self, data: dict) -> None:
        self.validator.validate(data)


class ChatMessageValidator(JSONSchemaValidator):
    pass


class StreamObservationValidator(JSONSchemaValidator):
    pass
