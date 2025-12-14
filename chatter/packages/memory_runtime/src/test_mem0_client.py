from __future__ import annotations

import unittest

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
                self.assertTrue(client.add_url.endswith("/v1/memories/"))
                self.assertTrue(client.search_url.endswith("/v2/memories/search"))
                self.assertEqual(normalized, client.base_url)


if __name__ == "__main__":
    unittest.main()
