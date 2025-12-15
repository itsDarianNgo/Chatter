#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict, Iterable

try:  # Optional for local dev; containers already supply env
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency managed via pyproject
    load_dotenv = None


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv_if_present() -> None:
    if load_dotenv is None:
        return
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


_load_dotenv_if_present()


def _extract_results(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("results"), list):
        return [entry for entry in payload.get("results", []) if isinstance(entry, dict)]
    if isinstance(payload.get("data"), list):
        return [entry for entry in payload.get("data", []) if isinstance(entry, dict)]
    return []


def _normalize_base_url(base_url: str) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    if parsed.scheme and parsed.netloc:
        path = re.sub(r"/{2,}", "/", parsed.path or "")
        path = path.rstrip("/")
        for suffix in ("/v1", "/v2"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                path = path.rstrip("/")
        normalized = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        return normalized.rstrip("/")

    trimmed = re.sub(r"(?<!:)/{2,}", "/", raw).rstrip("/")
    for suffix in ("/v1", "/v2"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)].rstrip("/")
    return trimmed


def _opt_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        value = default
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _request(method: str, url: str, headers: Dict[str, str], payload: Dict[str, Any] | None, timeout: int) -> Any:
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


def _iter_dict_candidates(payload: Any) -> Iterable[dict]:
    if isinstance(payload, dict):
        yield payload
        for key in ("results", "data"):
            maybe_list = payload.get(key)
            if isinstance(maybe_list, list):
                for entry in maybe_list:
                    if isinstance(entry, dict):
                        yield entry
        return
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                yield entry


def _extract_created_id(payload: Any) -> str | None:
    for candidate in _iter_dict_candidates(payload):
        for key in ("id", "memory_id", "uuid"):
            value = candidate.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return None


def main() -> int:
    api_key = os.getenv("MEM0_API_KEY")
    if not api_key:
        print("SKIP: missing MEM0_API_KEY")
        return 0

    base_url = _normalize_base_url(os.getenv("MEM0_BASE_URL", "https://api.mem0.ai"))
    org_id = os.getenv("MEM0_ORG_ID")
    project_id = os.getenv("MEM0_PROJECT_ID")
    timeout = int(os.getenv("MEM0_TIMEOUT_S", "10"))

    app_id = _opt_env("MEM0_APP_ID")
    user_id = _opt_env("MEM0_SMOKE_USER_ID", "chatter_mem0_smoke_user")
    run_id = _opt_env("MEM0_SMOKE_RUN_ID", "chatter_mem0_smoke_run")
    agent_id = _opt_env("MEM0_SMOKE_AGENT_ID")

    identifiers: Dict[str, Any] = {}
    if app_id:
        identifiers["app_id"] = app_id
    if user_id:
        identifiers["user_id"] = user_id
    if run_id:
        identifiers["run_id"] = run_id
    if agent_id:
        identifiers["agent_id"] = agent_id

    if not identifiers:
        print("FAIL: missing Mem0 identifiers; set one of MEM0_APP_ID, MEM0_SMOKE_USER_ID, MEM0_SMOKE_AGENT_ID, MEM0_SMOKE_RUN_ID")
        return 1

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    marker = str(uuid.uuid4())
    value = f"Chatter mem0 smoke marker {marker}"
    search_query = "smoke"

    add_payload: Dict[str, Any] = {
        **identifiers,
        "messages": [{"role": "user", "content": value}],
        "version": "v2",
        "output_format": "v1.1",
        "infer": False,
        "async_mode": False,
        "metadata": {"smoke_marker": marker},
    }
    search_payload: Dict[str, Any] = {
        "query": search_query,
        "filters": {**identifiers, "keywords": "smoke"},
        "limit": 10,
    }

    if org_id:
        add_payload["org_id"] = org_id
        search_payload["org_id"] = org_id
    if project_id:
        add_payload["project_id"] = project_id
        search_payload["project_id"] = project_id

    created_id: str | None = None
    try:
        add_url = f"{base_url}/v1/memories/"
        print(f"ADD URL: {add_url} METHOD: POST IDENTIFIERS: {json.dumps(identifiers, sort_keys=True)}")
        add_resp = _request("POST", add_url, headers, add_payload, timeout)
        created_id = _extract_created_id(add_resp)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: add memory error: {exc}")
        return 1

    try:
        search_url = f"{base_url}/v2/memories/search/"
        print(f"SEARCH URL: {search_url} METHOD: POST IDENTIFIERS: {json.dumps(identifiers, sort_keys=True)}")
        max_attempts = 3
        found = False
        for attempt in range(1, max_attempts + 1):
            search_resp = _request("POST", search_url, headers, search_payload, timeout)
            results = _extract_results(search_resp)
            for result in results:
                result_id = result.get("id") or result.get("memory_id") or result.get("uuid")
                if created_id and result_id and str(result_id).strip() == created_id:
                    found = True
                    break
                metadata = result.get("metadata") or {}
                if metadata.get("smoke_marker") == marker:
                    found = True
                    break
            if found:
                break
            if attempt < max_attempts:
                time.sleep(2)

        if not found and created_id:
            exact_payload = {
                "query": search_query,
                "filters": {**identifiers, "memory_ids": [created_id]},
                "limit": 3,
            }
            if org_id:
                exact_payload["org_id"] = org_id
            if project_id:
                exact_payload["project_id"] = project_id

            search_resp = _request("POST", search_url, headers, exact_payload, timeout)
            results = _extract_results(search_resp)
            for result in results:
                result_id = result.get("id") or result.get("memory_id") or result.get("uuid")
                if result_id and str(result_id).strip() == created_id:
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
                delete_url = f"{base_url}/v1/memories/{created_id}/"
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
