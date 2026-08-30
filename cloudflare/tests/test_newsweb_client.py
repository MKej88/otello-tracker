from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from newsweb_client import _post_json, parse_list_payload  # noqa: E402


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


class NewsWebPartialResponseTest(unittest.TestCase):
    def test_rejects_message_without_published_time(self) -> None:
        payload = {
            "data": {
                "messages": [
                    {
                        "messageId": 123,
                        "issuerId": 7759,
                        "issuerSign": "OTEC",
                        "markets": ["XOSL"],
                    }
                ],
                "overflow": False,
            }
        }

        with self.assertRaisesRegex(ValueError, "mangler gyldig publiseringstid"):
            parse_list_payload(payload)

    def test_rejects_changed_published_time_datatype(self) -> None:
        payload = {
            "data": {
                "messages": [
                    {
                        "messageId": 124,
                        "issuerId": 7759,
                        "issuerSign": "OTEC",
                        "markets": ["XOSL"],
                        "publishedTime": {"value": "2026-08-30T10:00:00Z"},
                    }
                ],
                "overflow": False,
            }
        }

        with self.assertRaisesRegex(ValueError, "mangler gyldig publiseringstid"):
            parse_list_payload(payload)


if __name__ == "__main__":
    unittest.main()
