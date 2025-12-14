from __future__ import annotations

import unittest
from unittest import mock

from .mem0_client import Mem0Client, _normalize_base_url


class Mem0ClientUrlTests(unittest.TestCase):
    def test_base_url_normalization(self) -> None:
        bases = [
            "https://api.mem0.ai",
            "https://api.mem0.ai/",
            "https://api.mem0.ai/v1",
            "https://api.mem0.ai/v1/",
            "https://api.mem0.ai/v2",
            "https://api.mem0.ai/v2/",
        ]

        for base in bases:
            normalized = _normalize_base_url(base)
            client = Mem0Client(api_key="dummy", base_url=base)
            with self.subTest(base=base):
                self.assertTrue(client.add_url.endswith("/v1/memories"))
                self.assertTrue(client.search_url.endswith("/v2/memories/search"))
                self.assertEqual(normalized, client.base_url)


class Mem0ClientRequestTests(unittest.TestCase):
    def test_search_uses_post_with_body(self) -> None:
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
        payload = {"query": "hello", "filters": {"user_id": "abc"}}

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            client.search_memories(payload)

        self.assertEqual(captured["method"], "POST")
        self.assertIsNotNone(captured["data"])
        self.assertTrue(captured["url"].endswith("/v2/memories/search"))


if __name__ == "__main__":
    unittest.main()
