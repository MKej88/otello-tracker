from __future__ import annotations

import json
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from newsweb_client import (  # noqa: E402
    _post_json,
    discover_otec_messages,
    fetch_attachment,
    fetch_message,
    parse_list_payload,
)


def _response(payload: dict[str, Any]) -> SimpleNamespace:
    async def text() -> str:
        return json.dumps(payload)

    return SimpleNamespace(ok=True, text=text, headers={})


def _list_response(
    messages: list[dict[str, Any]], *, overflow: bool
) -> SimpleNamespace:
    return _response(
        {
            "header": {"result.val": 0, "http.code": 200},
            "data": {"messages": messages, "overflow": overflow},
        }
    )


def _message(message_id: int, published_at: str, **extra: Any) -> dict[str, Any]:
    return {
        "messageId": message_id,
        "issuerId": 7759,
        "issuerSign": "OTEC",
        "markets": ["XOSL"],
        "publishedTime": published_at,
        **extra,
    }


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

    def test_rejects_invalid_published_time(self) -> None:
        payload = {
            "data": {
                "messages": [_message(125, "ikke-et-tidspunkt")],
                "overflow": False,
            }
        }

        with self.assertRaisesRegex(ValueError, "mangler gyldig publiseringstid"):
            parse_list_payload(payload)

    def test_rejects_changed_attachment_datatype_cleanly(self) -> None:
        payload = {
            "data": {
                "messages": [
                    {
                        "messageId": 125,
                        "issuerId": 7759,
                        "issuerSign": "OTEC",
                        "markets": ["XOSL"],
                        "publishedTime": "2026-08-30T10:00:00Z",
                        "attachments": [None],
                    }
                ],
                "overflow": False,
            }
        }

        with self.assertRaisesRegex(ValueError, "ugyldig vedleggsliste"):
            parse_list_payload(payload)

    def test_rejects_changed_category_datatype_cleanly(self) -> None:
        payload = {
            "data": {
                "messages": [
                    {
                        "messageId": 126,
                        "issuerId": 7759,
                        "issuerSign": "OTEC",
                        "markets": ["XOSL"],
                        "publishedTime": "2026-08-30T10:00:00Z",
                        "category": "buyback",
                    }
                ],
                "overflow": False,
            }
        }

        with self.assertRaisesRegex(ValueError, "ugyldig kategoriliste"):
            parse_list_payload(payload)


class NewsWebDiscoveryControlFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_reversed_date_range_before_request(self) -> None:
        request_made = False

        async def fetcher(url: str, **kwargs: object) -> SimpleNamespace:
            nonlocal request_made
            request_made = True
            return _list_response([], overflow=False)

        with self.assertRaisesRegex(ValueError, "from_date kan ikke være etter"):
            await discover_otec_messages(
                "2026-09-01", "2026-08-31", fetcher=fetcher
            )

        self.assertFalse(request_made)

    async def test_splits_overflow_window_without_date_gaps_or_overlap(self) -> None:
        requested_windows: list[tuple[str, str]] = []
        responses: Mapping[tuple[str, str], SimpleNamespace] = {
            ("2026-08-28", "2026-08-31"): _list_response([], overflow=True),
            ("2026-08-28", "2026-08-29"): _list_response(
                [_message(10, "2026-08-29T09:00:00Z")], overflow=False
            ),
            ("2026-08-30", "2026-08-31"): _list_response(
                [_message(11, "2026-08-30T09:00:00Z")], overflow=False
            ),
        }

        async def fetcher(url: str, **kwargs: object) -> SimpleNamespace:
            query = parse_qs(urlparse(url).query)
            window = (query["fromDate"][0], query["toDate"][0])
            requested_windows.append(window)
            return responses[window]

        messages = await discover_otec_messages(
            "2026-08-28", "2026-08-31", fetcher=fetcher
        )

        self.assertEqual(
            requested_windows,
            [
                ("2026-08-28", "2026-08-31"),
                ("2026-08-28", "2026-08-29"),
                ("2026-08-30", "2026-08-31"),
            ],
        )
        self.assertEqual([message.message_id for message in messages], [10, 11])

    async def test_rejects_single_day_overflow_instead_of_returning_partial_data(
        self,
    ) -> None:
        async def fetcher(url: str, **kwargs: object) -> SimpleNamespace:
            return _list_response([_message(20, "2026-08-31T10:00:00Z")], overflow=True)

        with self.assertRaisesRegex(ValueError, "overflow på enkelt dato 2026-08-31"):
            await discover_otec_messages("2026-08-31", "2026-08-31", fetcher=fetcher)

    async def test_removes_duplicates_and_superseded_messages(self) -> None:
        superseded = _message(
            30,
            "2026-08-31T08:00:00Z",
            correctedByMessageId=31,
        )
        correction = _message(
            31,
            "2026-08-31T09:00:00Z",
            correctionForMessageId=30,
        )

        async def fetcher(url: str, **kwargs: object) -> SimpleNamespace:
            return _list_response([correction, superseded, correction], overflow=False)

        messages = await discover_otec_messages(
            "2026-08-31", "2026-08-31", fetcher=fetcher
        )

        self.assertEqual([message.message_id for message in messages], [31])
        self.assertEqual(messages[0].correction_for_message_id, 30)


class NewsWebResourceIdentityTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_message_with_different_id_than_requested(self) -> None:
        payload = {
            "header": {"result.val": 0, "http.code": 200},
            "data": {
                "message": _message(
                    401,
                    "2026-08-31T10:00:00Z",
                    body="En gyldig meldingstekst",
                )
            },
        }

        async def fetcher(*args: object, **kwargs: object) -> SimpleNamespace:
            return _response(payload)

        with self.assertRaisesRegex(
            ValueError, "returnerte messageId 401, forventet 400"
        ):
            await fetch_message(400, fetcher=fetcher)

    async def test_rejects_html_error_page_returned_as_attachment(self) -> None:
        async def text() -> str:
            return "<html><body>midlertidig utilgjengelig</body></html>"

        async def fetcher(*args: object, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(ok=True, text=text, headers={})

        with self.assertRaisesRegex(ValueError, "er ikke en PDF"):
            await fetch_attachment(400, 12, fetcher=fetcher)


if __name__ == "__main__":
    unittest.main()
