from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable

from jsonschema import Draft202012Validator


def _load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_prompt_manifest(path: Path) -> Dict:
    manifest = _load_json(path)
    schema_path = path.parents[1] / "configs" / "schemas" / "prompt_manifest.schema.json"
    schema = _load_json(schema_path)
    Draft202012Validator(schema).validate(manifest)
    return manifest


def verify_prompt_files(manifest: Dict, base_dir: Path | str = ".") -> None:
    base_path = Path(base_dir)
    for prompt in manifest.get("prompts", []):
        prompt_path = base_path / prompt["path"]
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file missing: {prompt_path}")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_sha256(manifest: Dict, base_dir: Path | str = ".") -> None:
    base_path = Path(base_dir)
    for prompt in manifest.get("prompts", []):
        prompt_path = base_path / prompt["path"]
        digest = _sha256_file(prompt_path)
        if digest != prompt["sha256"]:
            raise ValueError(f"SHA mismatch for {prompt_path}: expected {prompt['sha256']}, got {digest}")
