from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from newsweb_client import _post_json  # noqa: E402


def _response(payload: dict[str, Any]) -> SimpleNamespace:
    async def text() -> str:
        return json.dumps(payload)

    return SimpleNamespace(ok=True, text=text, headers={})


class NewsWebStatusHeaderTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_missing_status_header(self) -> None:
        async def fetcher(*args: object, **kwargs: object) -> SimpleNamespace:
            return _response({"data": {"messages": [], "overflow": False}})

        with self.assertRaisesRegex(ValueError, "mangler statusheader"):
            await _post_json("https://example.com", fetcher=fetcher)

    async def test_rejects_incomplete_status_header(self) -> None:
        async def fetcher(*args: object, **kwargs: object) -> SimpleNamespace:
            return _response({"header": {"result.val": 0}, "data": {}})

        with self.assertRaisesRegex(ValueError, "ugyldig statusheader"):
            await _post_json("https://example.com", fetcher=fetcher)

    async def test_accepts_explicit_success_status(self) -> None:
        payload = {
            "header": {"result.val": 0, "http.code": 200},
            "data": {"messages": [], "overflow": False},
        }

        async def fetcher(*args: object, **kwargs: object) -> SimpleNamespace:
            return _response(payload)

        self.assertEqual(
            await _post_json("https://example.com", fetcher=fetcher),
            payload,
        )


if __name__ == "__main__":
    unittest.main()
