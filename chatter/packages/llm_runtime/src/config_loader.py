from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from jsonschema import Draft202012Validator


def _load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _repo_root_from_anchor(path: Path, anchor: str) -> Path:
    resolved = path.resolve()
    if anchor not in resolved.parts:
        return resolved.parent
    anchor_index = resolved.parts.index(anchor)
    return Path(*resolved.parts[:anchor_index])


def _validate(payload: Dict, schema_path: Path) -> Dict:
    schema = _load_json(schema_path)
    Draft202012Validator(schema).validate(payload)
    return payload


def load_llm_provider_config(path: Path) -> Dict:
    payload = _load_json(path)
    repo_root = _repo_root_from_anchor(path, "configs")
    schema_path = repo_root / "configs" / "schemas" / "llm_provider.schema.json"
    return _validate(payload, schema_path)


def load_memory_policy(path: Path) -> Dict:
    payload = _load_json(path)
    repo_root = _repo_root_from_anchor(path, "configs")
    schema_path = repo_root / "configs" / "schemas" / "memory_policy.schema.json"
    return _validate(payload, schema_path)
