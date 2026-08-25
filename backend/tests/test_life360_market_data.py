from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from life360_market_data import (  # noqa: E402
    LIFE360_CONTROL_SYMBOLS,
    LIFE360_REQUIRED_SYMBOL,
    _download_chart_with_host_fallback,
    build_yahoo_chart_url,
    parse_yahoo_chart,
)


def _payload(*, symbol: str = "LIF", currency: str = "USD") -> bytes:
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": symbol,
                            "currency": currency,
                            "exchangeName": "NMS" if symbol == "LIF" else "ASX",
                            "exchangeTimezoneName": (
                                "America/New_York" if symbol == "LIF" else "Australia/Sydney"
                            ),
                        },
                        "timestamp": [1787251800, 1787338200, 1787424600],
                        "indicators": {
                            "quote": [
                                {
                                    "close": [44.0, None, 44.66],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    ).encode()


class FakeResponse:
    def __init__(self, payload: bytes = b"", *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.ok = 200 <= status < 300
        self.headers = {"content-length": str(len(payload))}

    async def text(self):
        return self.payload.decode("utf-8")


def test_yahoo_chart_url_requests_bounded_daily_history() -> None:
    url = build_yahoo_chart_url("360.AX", "2019-05-10", "2019-05-31")
    assert "/360.AX?" in url
    assert "interval=1d" in url
    assert "events=history" in url
    assert "includeAdjustedClose=false" in url


def test_yahoo_chart_url_can_switch_provider_host() -> None:
    url = build_yahoo_chart_url(
        "LIF",
        "2026-08-20",
        "2026-08-24",
        base_url="https://query2.finance.yahoo.com/v8/finance/chart",
    )
    assert url.startswith("https://query2.finance.yahoo.com/v8/finance/chart/LIF?")


def test_yahoo_chart_download_falls_back_to_second_endpoint() -> None:
    calls: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        calls.append(url)
        if "query1.finance.yahoo.com" in url:
            return FakeResponse(status=503)
        return FakeResponse(_payload())

    url, payload, provider = asyncio.run(
        _download_chart_with_host_fallback(
            "LIF",
            "2026-08-20",
            "2026-08-24",
            fetcher=fake_fetch,
        )
    )
    assert len(calls) == 2
    assert "query1.finance.yahoo.com" in calls[0]
    assert "query2.finance.yahoo.com" in calls[1]
    assert "query2.finance.yahoo.com" in url
    assert provider == "https://query2.finance.yahoo.com/v8/finance/chart"
    assert payload == _payload()


def test_lif_is_required_while_asx_is_control_series() -> None:
    assert LIFE360_REQUIRED_SYMBOL == "LIF"
    assert LIFE360_CONTROL_SYMBOLS == {"360.AX"}


def test_parser_accepts_lif_and_skips_null_close() -> None:
    result = parse_yahoo_chart(_payload(), expected_symbol="LIF", expected_currency="USD")
    assert result["symbol"] == "LIF"
    assert result["currency"] == "USD"
    assert len(result["rows"]) == 2
    assert result["rows"][-1]["price"] == "44.66"


def test_parser_accepts_asx_history_in_aud() -> None:
    result = parse_yahoo_chart(
        _payload(symbol="360.AX", currency="AUD"),
        expected_symbol="360.AX",
        expected_currency="AUD",
    )
    assert result["symbol"] == "360.AX"
    assert result["currency"] == "AUD"
    assert result["exchange_timezone"] == "Australia/Sydney"


@pytest.mark.parametrize(
    ("expected_symbol", "expected_currency", "match"),
    [
        ("WRONG", "USD", "matcher ikke forventet"),
        ("LIF", "AUD", "valuta"),
    ],
)
def test_parser_rejects_wrong_identity(expected_symbol: str, expected_currency: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_yahoo_chart(
            _payload(),
            expected_symbol=expected_symbol,
            expected_currency=expected_currency,
        )
