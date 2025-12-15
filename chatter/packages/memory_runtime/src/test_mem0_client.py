from __future__ import annotations

import json
import unittest
from unittest import mock

from .mem0_client import Mem0Client, _normalize_base_url


class Mem0ClientUrlTests(unittest.TestCase):
    def test_base_url_normalization(self) -> None:
        bases = [
            "https://api.mem0.ai",
            "https://api.mem0.ai/",
            "https://api.mem0.ai//",
            "https://api.mem0.ai/v1",
            "https://api.mem0.ai/v1/",
            "https://api.mem0.ai//v1",
            "https://api.mem0.ai///v1//",
            "https://api.mem0.ai/v2",
            "https://api.mem0.ai/v2/",
            "https://api.mem0.ai//v2",
            "https://api.mem0.ai///v2//",
        ]

        for base in bases:
            normalized = _normalize_base_url(base)
            client = Mem0Client(api_key="dummy", base_url=base)
            with self.subTest(base=base):
                self.assertTrue(client.add_url.endswith("/v1/memories/"))
                self.assertTrue(client.search_url.endswith("/v2/memories/search/"))
                self.assertEqual(normalized, client.base_url)


class Mem0ClientRequestTests(unittest.TestCase):
    def test_add_lifts_identifiers_from_filters_and_strips_filters(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout=None):  # type: ignore[override]
            captured["method"] = req.get_method()
            captured["data"] = req.data
            captured["url"] = req.full_url

            class Resp:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *exc_info):
                    return False

                def read(self_inner):
                    return b"{}"

            return Resp()

        client = Mem0Client(api_key="dummy", base_url="https://api.mem0.ai/v2/")
        payload = {
            "filters": {"agent_id": " abc "},
            "messages": [{"role": "user", "content": "hi"}],
            "infer": False,
            "async_mode": False,
        }

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            client.add_memory(payload)

        self.assertEqual(captured["method"], "POST")
        self.assertIsNotNone(captured["data"])
        self.assertTrue(captured["url"].endswith("/v1/memories/"))
        decoded = json.loads(captured["data"].decode("utf-8"))
        self.assertNotIn("filters", decoded)
        self.assertEqual(decoded.get("agent_id"), "abc")

    def test_search_moves_top_level_identifiers_into_filters(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout=None):  # type: ignore[override]
            captured["method"] = req.get_method()
            captured["data"] = req.data
            captured["url"] = req.full_url

            class Resp:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *exc_info):
                    return False

                def read(self_inner):
                    return b"{}"

            return Resp()

        client = Mem0Client(api_key="dummy", base_url="https://api.mem0.ai/v1/")
        payload = {"query": "hello", "user_id": " abc "}

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            client.search_memories(payload)

        self.assertEqual(captured["method"], "POST")
        self.assertIsNotNone(captured["data"])
        self.assertTrue(captured["url"].endswith("/v2/memories/search/"))
        decoded = json.loads(captured["data"].decode("utf-8"))
        self.assertNotIn("user_id", decoded)
        self.assertEqual(decoded.get("filters", {}).get("user_id"), "abc")

    def test_add_identifiers_required_raises_before_http(self) -> None:
        client = Mem0Client(api_key="dummy", base_url="https://api.mem0.ai/")
        with mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(ValueError) as ctx:
                client.add_memory({"messages": [{"role": "user", "content": "hi"}]})
            urlopen.assert_not_called()
        self.assertIn("mem0_identifiers_required", str(ctx.exception))

    def test_search_identifiers_required_raises_before_http(self) -> None:
        client = Mem0Client(api_key="dummy", base_url="https://api.mem0.ai/")
        with mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(ValueError) as ctx:
                client.search_memories({"query": "hello"})
            urlopen.assert_not_called()
        self.assertIn("mem0_identifiers_required", str(ctx.exception))

    def test_app_id_satisfies_identifier_requirement_for_add_and_search(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout=None):  # type: ignore[override]
            captured["url"] = req.full_url
            captured["data"] = req.data

            class Resp:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *exc_info):
                    return False

                def read(self_inner):
                    return b"{}"

            return Resp()

        client = Mem0Client(api_key="dummy", base_url="https://api.mem0.ai/", app_id="my_app")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            client.add_memory({"messages": [{"role": "user", "content": "hi"}]})

        decoded = json.loads(captured["data"].decode("utf-8"))
        self.assertTrue(str(captured.get("url", "")).endswith("/v1/memories/"))
        self.assertEqual(decoded.get("app_id"), "my_app")
        self.assertNotIn("filters", decoded)

        captured.clear()
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            client.search_memories({"query": "hello"})

        decoded = json.loads(captured["data"].decode("utf-8"))
        self.assertTrue(str(captured.get("url", "")).endswith("/v2/memories/search/"))
        self.assertEqual(decoded.get("filters", {}).get("app_id"), "my_app")


if __name__ == "__main__":
    unittest.main()
