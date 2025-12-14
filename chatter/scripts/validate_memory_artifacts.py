#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from packages.memory_runtime.src.policy import load_memory_policy  # noqa: E402
from packages.memory_runtime.src.validate import (  # noqa: E402
    validate_memory_item_dict,
    validate_memory_stub_fixtures,
)


def load_json(path: Path) -> Dict:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return json.loads(normalized)


def validate_good_items(repo_root: Path) -> bool:
    schema_path = repo_root / "data" / "schemas" / "memory_item.schema.json"
    good_dir = repo_root / "data" / "fixtures" / "memory_items"
    good_paths = sorted(good_dir.glob("good_*.json"))
    all_ok = True
    for path in good_paths:
        payload = load_json(path)
        try:
            validate_memory_item_dict(payload, schema_path)
            print(f"[OK] good fixture valid: {path.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] good fixture invalid ({path.name}): {exc}")
            all_ok = False
    return all_ok


def validate_bad_items(repo_root: Path) -> bool:
    schema_path = repo_root / "data" / "schemas" / "memory_item.schema.json"
    bad_dir = repo_root / "data" / "fixtures" / "memory_items"
    bad_paths = sorted(bad_dir.glob("bad_*.json"))
    all_ok = True
    for path in bad_paths:
        payload = load_json(path)
        try:
            validate_memory_item_dict(payload, schema_path)
            print(f"[FAIL] bad fixture unexpectedly valid: {path.name}")
            all_ok = False
        except Exception as exc:  # noqa: BLE001
            print(f"[OK] bad fixture rejected ({path.name}): {exc}")
    return all_ok


def validate_stub(repo_root: Path) -> bool:
    fixture_path = repo_root / "data" / "memory_stub" / "fixtures" / "demo.json"
    try:
        payload = load_json(fixture_path)
        validate_memory_stub_fixtures(payload)
        print("[OK] memory stub fixtures valid")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] memory stub fixtures invalid: {exc}")
        return False


def validate_policies(repo_root: Path) -> bool:
    config_dir = repo_root / "configs" / "memory"
    config_paths = sorted(config_dir.glob("*.json"))
    all_ok = True
    for path in config_paths:
        try:
            load_memory_policy(path)
            print(f"[OK] memory policy valid: {path.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] memory policy invalid ({path.name}): {exc}")
            all_ok = False
    return all_ok


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate memory artifacts for Milestone 3C-A")
    _ = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = REPO_ROOT
    checks = [
        validate_good_items(repo_root),
        validate_bad_items(repo_root),
        validate_stub(repo_root),
        validate_policies(repo_root),
    ]

    failed = [idx for idx, ok in enumerate(checks) if not ok]
    if failed:
        print("Memory artifact validation FAILED")
        return 1

    print("Memory artifact validation PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
