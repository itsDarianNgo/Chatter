from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict

logger = logging.getLogger(__name__)

_IDENTIFIER_KEYS: tuple[str, ...] = ("app_id", "user_id", "agent_id", "run_id")


def _normalized_identifier_value(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        value = raw_value.strip()
    else:
        value = str(raw_value).strip()
    return value or None


def _has_identifiers(mapping: Dict[str, Any]) -> bool:
    return any(isinstance(mapping.get(key), str) and mapping.get(key).strip() for key in _IDENTIFIER_KEYS)


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


class Mem0Client:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.mem0.ai",
        timeout_s: int = 10,
        app_id: str | None = None,
        org_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = _normalize_base_url(base_url)
        self.add_url = f"{self.base_url}/v1/memories/"
        self.search_url = f"{self.base_url}/v2/memories/search/"
        self.delete_url_prefix = f"{self.base_url}/v1/memories/"
        self.timeout_s = timeout_s
        self.app_id = (app_id or "").strip() or None
        self.org_id = org_id
        self.project_id = project_id

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if payload is None and method.upper() in {"POST", "PUT", "PATCH"}:
            payload = {}
        data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                body = resp.read()
                if not body:
                    return {}
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - surfaced to caller
            text = exc.read().decode("utf-8") if hasattr(exc, "read") else str(exc)
            logger.debug("mem0 http error %s: %s", exc.code, text)
            raise

    def _normalize_add_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(payload)
        raw_filters = enriched.pop("filters", None)
        filters: Dict[str, Any] = raw_filters if isinstance(raw_filters, dict) else {}

        for key in _IDENTIFIER_KEYS:
            existing = _normalized_identifier_value(enriched.get(key))
            if existing:
                enriched[key] = existing
                continue

            lifted = _normalized_identifier_value(filters.get(key)) if filters else None
            if lifted:
                enriched[key] = lifted
            else:
                enriched.pop(key, None)

        if self.app_id and not _normalized_identifier_value(enriched.get("app_id")):
            enriched["app_id"] = self.app_id

        for key in _IDENTIFIER_KEYS:
            normalized = _normalized_identifier_value(enriched.get(key))
            if normalized:
                enriched[key] = normalized
            else:
                enriched.pop(key, None)

        if not _has_identifiers(enriched):
            raise ValueError("mem0_identifiers_required: one of app_id, user_id, agent_id, run_id must be set")

        return enriched

    def _normalize_search_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(payload)
        filters: Dict[str, Any] = {}
        raw_filters = enriched.get("filters")
        if isinstance(raw_filters, dict):
            filters.update(raw_filters)

        for key in _IDENTIFIER_KEYS:
            if key not in enriched:
                continue
            moved = _normalized_identifier_value(enriched.pop(key))
            if moved:
                filters[key] = moved

        for key in list(_IDENTIFIER_KEYS):
            if key not in filters:
                continue
            normalized = _normalized_identifier_value(filters.get(key))
            if normalized:
                filters[key] = normalized
            else:
                filters.pop(key, None)

        if self.app_id and not _normalized_identifier_value(filters.get("app_id")):
            filters["app_id"] = self.app_id

        if not _has_identifiers(filters):
            raise ValueError("mem0_identifiers_required: one of app_id, user_id, agent_id, run_id must be set")

        enriched["filters"] = filters
        return enriched

    def _enrich_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(payload)
        if self.org_id:
            enriched.setdefault("org_id", self.org_id)
        if self.project_id:
            enriched.setdefault("project_id", self.project_id)
        return enriched

    def add_memory(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize_add_payload(payload)
        return self._request("POST", self.add_url, self._enrich_payload(normalized))

    def search_memories(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize_search_payload(payload)
        return self._request("POST", self.search_url, self._enrich_payload(normalized))

    def delete_memory(self, memory_id: str) -> None:
        url = f"{self.delete_url_prefix}{memory_id}/"
        self._request("DELETE", url, None)


__all__ = ["Mem0Client", "_normalize_base_url"]
