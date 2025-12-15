#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, Tuple

from jsonschema import Draft202012Validator


SchemaConfig = Dict[str, Path]


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def gather_paths(root: Path) -> Tuple[Path, Path]:
    valid_dir = root / "valid"
    invalid_dir = root / "invalid"
    return valid_dir, invalid_dir


def validate_schema(name: str, schema_path: Path) -> bool:
    print(f"Checking schema for {name}: {schema_path}")
    if not schema_path.exists():
        print(f"  [FAIL] Schema file missing: {schema_path}")
        return False

    try:
        schema = load_json(schema_path)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] Could not load schema: {exc}")
        return False

    try:
        Draft202012Validator.check_schema(schema)
        print("  [OK] Schema is valid against Draft 2020-12 metaschema")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] Schema validation error: {exc}")
        return False


def validate_fixture(
    fixture_path: Path, validator: Draft202012Validator, expect_valid: bool
) -> bool:
    try:
        instance = load_json(fixture_path)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {fixture_path}: unable to load JSON ({exc})")
        return False

    try:
        validator.validate(instance)
        if expect_valid:
            print(f"  [OK] {fixture_path}")
            return True
        print(f"  [FAIL] {fixture_path}: expected validation failure but passed")
        return False
    except Exception as exc:  # noqa: BLE001
        if expect_valid:
            print(f"  [FAIL] {fixture_path}: validation failed ({exc})")
            return False
        print(f"  [OK] {fixture_path}: correctly failed validation ({exc})")
        return True


def validate_fixtures(
    name: str, version: str, schema_path: Path, base_fixture_dir: Path
) -> Tuple[int, int]:
    if not schema_path.exists():
        print(f"[FAIL] Schema missing for {name}: {schema_path}")
        return 0, 1

    try:
        schema = load_json(schema_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Could not load schema for {name}: {exc}")
        return 0, 1

    validator = Draft202012Validator(schema)
    valid_dir, invalid_dir = gather_paths(base_fixture_dir)

    passed = 0
    failed = 0

    if not base_fixture_dir.exists():
        print(f"[WARN] Fixture directory missing for {name} {version}: {base_fixture_dir}")
        return passed, failed

    for label, directory, expect_valid in (
        ("valid", valid_dir, True),
        ("invalid", invalid_dir, False),
    ):
        if not directory.exists():
            print(f"[WARN] Missing {label} fixtures for {name} {version}: {directory}")
            continue
        print(f"Validating {label} fixtures for {name} {version}: {directory}")
        for path in sorted(directory.glob("*.json")):
            if validate_fixture(path, validator, expect_valid):
                passed += 1
            else:
                failed += 1
        if not any(directory.glob("*.json")):
            print(f"  [WARN] No {label} fixtures found in {directory}")

    return passed, failed


def build_schema_map(repo_root: Path) -> SchemaConfig:
    return {
        "StreamContext": repo_root / "packages/protocol/jsonschema/stream_context.schema.json",
        "ChatMessage": repo_root / "packages/protocol/jsonschema/chat_message.schema.json",
        "TrendsSnapshot": repo_root / "packages/protocol/jsonschema/trends_snapshot.schema.json",
        "StreamFrame": repo_root / "packages/protocol/jsonschema/stream_frame.v1.schema.json",
        "StreamTranscriptSegment": repo_root / "packages/protocol/jsonschema/stream_transcript_segment.v1.schema.json",
        "StreamObservation": repo_root / "packages/protocol/jsonschema/stream_observation.v1.schema.json",
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate protocol schemas and fixtures")
    parser.add_argument(
        "--only",
        choices=[
            "StreamContext",
            "ChatMessage",
            "TrendsSnapshot",
            "StreamFrame",
            "StreamTranscriptSegment",
            "StreamObservation",
        ],
        help="Validate a single schema by name",
    )
    parser.add_argument(
        "--version",
        default="1.0.0",
        help="Version directory to validate (default: 1.0.0)",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(__file__).resolve().parents[2]
    schema_map = build_schema_map(repo_root)

    targets = [args.only] if args.only else sorted(schema_map.keys())

    total_passed = 0
    total_failed = 0

    for name in targets:
        schema_path = schema_map[name]
        fixtures_dir = repo_root / "data/schemas" / name / args.version

        schema_ok = validate_schema(name, schema_path)
        if not schema_ok:
            total_failed += 1
            continue

        passed, failed = validate_fixtures(name, args.version, schema_path, fixtures_dir)
        total_passed += passed
        total_failed += failed

    print("\nSummary:")
    print(f"  Passed: {total_passed}")
    print(f"  Failed: {total_failed}")

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
