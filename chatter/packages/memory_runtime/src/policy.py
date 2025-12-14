from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

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


def load_memory_policy(path: Path) -> Dict:
    payload = _load_json(path)
    repo_root = _repo_root_from_anchor(path, "configs")
    schema_path = repo_root / "configs" / "schemas" / "memory_policy.schema.json"
    schema = _load_json(schema_path)
    Draft202012Validator(schema).validate(payload)
    return payload


def is_category_allowed(policy: Dict, category: str) -> bool:
    if not category:
        return False
    if category in policy.get("deny_categories", []):
        return False
    allowed = policy.get("allow_categories") or []
    if allowed and category not in allowed:
        return False
    return True


def is_scope_allowed(policy: Dict, scope: str) -> bool:
    scopes = policy.get("scopes") or []
    return bool(scope) and scope in scopes


def should_store_item(policy: Dict, item: Dict) -> Tuple[bool, str]:
    if not policy.get("enabled", False):
        return False, "policy_disabled"

    scope = item.get("scope")
    if not is_scope_allowed(policy, scope):
        return False, "scope_not_allowed"

    category = item.get("category", "")
    if not is_category_allowed(policy, category):
        if category in policy.get("deny_categories", []):
            return False, "category_denied"
        return False, "category_not_allowed"

    confidence = item.get("confidence", 0)
    min_conf = policy.get("write_rules", {}).get("min_confidence", 0)
    if confidence < min_conf:
        return False, "low_confidence"

    ttl_days = item.get("ttl_days")
    ttl_default = policy.get("ttl_days_default")
    if ttl_days is None:
        if ttl_default is None:
            return False, "ttl_missing"
        item["ttl_days"] = ttl_default
    else:
        if ttl_days < 1:
            return False, "ttl_invalid"
        if ttl_default is not None and ttl_days > ttl_default:
            item["ttl_days"] = ttl_default

    return True, "ok"


__all__ = [
    "load_memory_policy",
    "is_category_allowed",
    "is_scope_allowed",
    "should_store_item",
]
