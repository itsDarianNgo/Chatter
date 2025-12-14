from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from jsonschema import Draft202012Validator


def _load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_llm_stub_fixtures(path: Path) -> None:
    payload = _load_json(path)
    resolved = path.resolve()
    repo_root = Path(*resolved.parts[: resolved.parts.index("data")]) if "data" in resolved.parts else resolved.parent
    schema_path = repo_root / "data" / "schemas" / "llm_stub_fixture.schema.json"
    schema = _load_json(schema_path)
    Draft202012Validator(schema).validate(payload)
