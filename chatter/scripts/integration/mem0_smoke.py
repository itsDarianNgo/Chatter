#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict


def _extract_results(payload: Dict[str, Any]) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("results"), list):
        return payload.get("results", [])
    if isinstance(payload.get("data"), list):
        return payload.get("data", [])
    return []


def _normalize_base_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    for suffix in ("/v1", "/v2"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
            trimmed = trimmed.rstrip("/")
    return trimmed or base_url.rstrip("/")


def _request(method: str, url: str, headers: Dict[str, str], payload: Dict[str, Any] | None, timeout: int) -> Dict[str, Any]:
    if payload is None and method.upper() in {"POST", "PUT", "PATCH"}:
        payload = {}
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read()
            if not body:
                return {}
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"HTTP {exc.code} {exc.reason} for {method} {url}: {body}") from exc


def main() -> int:
    api_key = os.getenv("MEM0_API_KEY")
    if not api_key:
        print("SKIP: missing MEM0_API_KEY")
        return 0

    base_url = _normalize_base_url(os.getenv("MEM0_BASE_URL", "https://api.mem0.ai"))
    org_id = os.getenv("MEM0_ORG_ID")
    project_id = os.getenv("MEM0_PROJECT_ID")
    timeout = int(os.getenv("MEM0_TIMEOUT_S", "10"))

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    user_id = f"chatter_mem0_smoke_{int(time.time())}_{os.getpid()}"
    marker = str(uuid.uuid4())
    value = f"Chatter mem0 smoke marker {marker}"

    add_payload: Dict[str, Any] = {
        "user_id": user_id,
        "messages": [{"role": "user", "content": value}],
        "version": "v2",
        "output_format": "v1.1",
        "infer": False,
        "async_mode": False,
    }
    search_payload: Dict[str, Any] = {
        "query": marker,
        "filters": {"user_id": user_id},
        "limit": 3,
    }

    if org_id:
        add_payload["org_id"] = org_id
        search_payload["org_id"] = org_id
    if project_id:
        add_payload["project_id"] = project_id
        search_payload["project_id"] = project_id

    created_id: str | None = None
    try:
        add_url = f"{base_url}/v1/memories"
        print(f"ADD URL: {add_url} METHOD: POST")
        add_resp = _request("POST", add_url, headers, add_payload, timeout)
        created_id = add_resp.get("id") or add_resp.get("memory_id")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: add memory error: {exc}")
        return 1

    try:
        search_url = f"{base_url}/v2/memories/search"
        print(f"SEARCH URL: {search_url} METHOD: POST")
        search_resp = _request("POST", search_url, headers, search_payload, timeout)
        results = _extract_results(search_resp)
        found = False
        for result in results:
            text = result.get("memory") or result.get("content") or result.get("text") or ""
            metadata = result.get("metadata") or {}
            candidate_value = metadata.get("value") or text
            if marker in str(candidate_value):
                found = True
                break
        if not found:
            print("FAIL: added memory not found in search results")
            return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: search error: {exc}")
        return 1
    finally:
        if created_id:
            try:
                delete_url = f"{base_url}/v1/memories/{created_id}"
                print(f"DELETE URL: {delete_url} METHOD: DELETE")
                _request("DELETE", delete_url, headers, None, timeout)
            except Exception:
                pass

    print("PASS: mem0 smoke test succeeded")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:  # pragma: no cover - surface readable errors
        print(f"FAIL: HTTP error {exc.code}: {exc.reason}")
        sys.exit(1)
