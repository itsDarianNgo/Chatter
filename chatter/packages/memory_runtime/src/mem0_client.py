from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _normalize_base_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    for suffix in ("/v1", "/v2"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
            trimmed = trimmed.rstrip("/")
    return trimmed or base_url.rstrip("/")


class Mem0Client:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.mem0.ai",
        timeout_s: int = 10,
        org_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = _normalize_base_url(base_url)
        self.add_url = f"{self.base_url}/v1/memories/"
        self.search_url = f"{self.base_url}/v2/memories/search"
        self.delete_url_prefix = f"{self.base_url}/v1/memories/"
        self.timeout_s = timeout_s
        self.org_id = org_id
        self.project_id = project_id

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
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

    def _enrich_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(payload)
        if self.org_id:
            enriched.setdefault("org_id", self.org_id)
        if self.project_id:
            enriched.setdefault("project_id", self.project_id)
        return enriched

    def add_memory(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", self.add_url, self._enrich_payload(payload))

    def search_memories(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", self.search_url, self._enrich_payload(payload))

    def delete_memory(self, memory_id: str) -> None:
        url = f"{self.delete_url_prefix}{memory_id}"
        self._request("DELETE", url, None)


__all__ = ["Mem0Client", "_normalize_base_url"]
