#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, Tuple

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from packages.llm_runtime.src.hash_utils import canonical_prompt_sha256  # noqa: E402


def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_payload(label: str, payload: Dict, schema_path: Path) -> Tuple[bool, str]:
    try:
        schema = load_json(schema_path)
    except Exception as exc:  # noqa: BLE001
        return False, f"[FAIL] {label}: unable to load schema {schema_path} ({exc})"

    try:
        Draft202012Validator(schema).validate(payload)
        return True, f"[OK] {label}: valid"
    except Exception as exc:  # noqa: BLE001
        return False, f"[FAIL] {label}: {exc}"


def validate_provider(repo_root: Path) -> bool:
    schema_path = repo_root / "configs/schemas/llm_provider.schema.json"
    provider_paths = [
        ("llm provider (stub)", repo_root / "configs/llm/providers/stub.json"),
        ("llm provider (litellm example)", repo_root / "configs/llm/providers/litellm.example.json"),
    ]

    all_ok = True
    for label, config_path in provider_paths:
        payload = load_json(config_path)
        ok, msg = validate_payload(label, payload, schema_path)
        print(msg)
        all_ok = all_ok and ok
    return all_ok


def validate_memory_policy(repo_root: Path) -> bool:
    config_path = repo_root / "configs/memory/default_policy.json"
    schema_path = repo_root / "configs/schemas/memory_policy.schema.json"
    payload = load_json(config_path)
    ok, msg = validate_payload("memory policy", payload, schema_path)
    print(msg)
    return ok


def validate_prompt_manifest(repo_root: Path) -> bool:
    manifest_path = repo_root / "prompts/manifest.json"
    schema_path = repo_root / "configs/schemas/prompt_manifest.schema.json"
    manifest = load_json(manifest_path)
    ok, msg = validate_payload("prompt manifest", manifest, schema_path)
    print(msg)
    if not ok:
        return False

    all_ok = True
    for entry in manifest.get("prompts", []):
        prompt_path = repo_root / entry["path"]
        if not prompt_path.exists():
            print(f"[FAIL] prompt missing: {prompt_path}")
            all_ok = False
            continue
        digest = canonical_prompt_sha256(prompt_path)
        if digest != entry["sha256"]:
            print(
                f"[FAIL] prompt sha mismatch for {prompt_path}: expected {entry['sha256']} got {digest}"
            )
            all_ok = False
    return all_ok


def validate_stub_fixtures(repo_root: Path) -> bool:
    fixture_path = repo_root / "data/llm_stub/fixtures/demo.json"
    schema_path = repo_root / "data/schemas/llm_stub_fixture.schema.json"
    payload = load_json(fixture_path)
    ok, msg = validate_payload("llm stub fixtures", payload, schema_path)
    print(msg)
    return ok


def validate_llm_generator_init(repo_root: Path) -> bool:
    try:
        from apps.persona_workers.src.generator import LLMReplyGenerator
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] import LLMReplyGenerator: {exc}")
        return False

    try:
        generator = LLMReplyGenerator(
            base_path=repo_root,
            provider_config_path="configs/llm/providers/stub.json",
            prompt_manifest_path="prompts/manifest.json",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] LLMReplyGenerator init: {exc}")
        return False

    if not isinstance(getattr(generator, "max_output_chars", None), int):
        print("[FAIL] LLMReplyGenerator max_output_chars missing or not int")
        return False
    if generator.max_output_chars <= 0:
        print("[FAIL] LLMReplyGenerator max_output_chars not positive")
        return False

    print("[OK] LLMReplyGenerator init and max_output_chars present")
    return True


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate LLM artifacts for Milestone 3A")
    _ = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(__file__).resolve().parents[1]

    checks = [
        validate_provider(repo_root),
        validate_memory_policy(repo_root),
        validate_prompt_manifest(repo_root),
        validate_stub_fixtures(repo_root),
        validate_llm_generator_init(repo_root),
    ]

    failed = [idx for idx, ok in enumerate(checks) if not ok]
    if failed:
        print("LLM artifact validation FAILED")
        return 1

    print("LLM artifact validation PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
