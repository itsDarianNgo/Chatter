from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from jsonschema import Draft202012Validator, RefResolver

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_json_normalized(path: Path) -> Dict:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return json.loads(normalized)


def _validator_for(schema_path: Path, store: Dict | None = None) -> Draft202012Validator:
    schema = _load_json_normalized(schema_path)
    resolver = RefResolver(
        base_uri=schema_path.resolve().parent.as_uri() + "/",
        referrer=schema,
        store=store or {},
    )
    return Draft202012Validator(schema, resolver=resolver)


def validate_memory_item_dict(item_dict: Dict, schema_path: Path | None = None) -> None:
    schema_path = schema_path or (REPO_ROOT / "data" / "schemas" / "memory_item.schema.json")
    validator = _validator_for(schema_path)
    validator.validate(item_dict)


def validate_memory_stub_fixtures(payload: Dict, schema_path: Path | None = None) -> None:
    schema_path = schema_path or (REPO_ROOT / "data" / "schemas" / "memory_stub_fixtures.schema.json")
    memory_item_schema_path = REPO_ROOT / "data" / "schemas" / "memory_item.schema.json"
    memory_item_schema = _load_json_normalized(memory_item_schema_path)
    store = {
        "memory_item.schema.json": memory_item_schema,
        memory_item_schema_path.resolve().as_uri(): memory_item_schema,
    }
    validator = _validator_for(schema_path, store=store)
    validator.validate(payload)


def load_schema(schema_name: str) -> Dict:
    schema_path = REPO_ROOT / "data" / "schemas" / schema_name
    return _load_json_normalized(schema_path)


__all__ = [
    "validate_memory_item_dict",
    "validate_memory_stub_fixtures",
    "load_schema",
]
