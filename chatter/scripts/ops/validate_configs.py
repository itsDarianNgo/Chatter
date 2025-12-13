#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from jsonschema import Draft202012Validator

SchemaConfig = Dict[str, Path]
FixtureMap = Dict[str, List[Tuple[Path, bool]]]


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_json_files(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.json"))


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


def validate_fixture(path: Path, validator: Draft202012Validator, expect_valid: bool) -> bool:
    try:
        instance = load_json(path)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {path}: unable to load JSON ({exc})")
        return False

    try:
        validator.validate(instance)
        if expect_valid:
            print(f"  [OK] {path}")
            return True
        print(f"  [FAIL] {path}: expected validation failure but passed")
        return False
    except Exception as exc:  # noqa: BLE001
        if expect_valid:
            print(f"  [FAIL] {path}: validation failed ({exc})")
            return False
        print(f"  [OK] {path}: correctly failed validation ({exc})")
        return True


def validate_fixture_dir(name: str, directory: Path, validator: Draft202012Validator, expect_valid: bool) -> Tuple[int, int]:
    passed = 0
    failed = 0

    files = list_json_files(directory)
    label = "valid" if expect_valid else "invalid"

    if not files:
        print(f"[WARN] No {label} fixtures found for {name}: {directory}")
        return passed, failed

    print(f"Validating {label} fixtures for {name}: {directory}")
    for path in files:
        if validate_fixture(path, validator, expect_valid):
            passed += 1
        else:
            failed += 1

    return passed, failed


def build_schema_map(repo_root: Path) -> SchemaConfig:
    return {
        "persona": repo_root / "configs/schemas/persona.schema.json",
        "room": repo_root / "configs/schemas/room.schema.json",
        "moderation": repo_root / "configs/schemas/moderation.schema.json",
    }


def build_fixture_map(repo_root: Path) -> FixtureMap:
    return {
        "persona": [(repo_root / "configs/personas", True)],
        "room": [(repo_root / "configs/rooms", True)],
        "moderation": [(repo_root / "configs/moderation", True)],
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate config schemas and example configs")
    parser.add_argument(
        "--only",
        choices=["persona", "room", "moderation"],
        help="Validate a single config schema",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(__file__).resolve().parents[2]
    schema_map = build_schema_map(repo_root)
    fixture_map = build_fixture_map(repo_root)

    targets = [args.only] if args.only else sorted(schema_map.keys())

    total_passed = 0
    total_failed = 0

    for name in targets:
        schema_path = schema_map[name]
        fixtures = fixture_map.get(name, [])

        schema_ok = validate_schema(name, schema_path)
        if not schema_ok:
            total_failed += 1
            continue

        validator = Draft202012Validator(load_json(schema_path))
        for directory, expect_valid in fixtures:
            passed, failed = validate_fixture_dir(name, directory, validator, expect_valid)
            total_passed += passed
            total_failed += failed

    print("\nSummary:")
    print(f"  Passed: {total_passed}")
    print(f"  Failed: {total_failed}")

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
