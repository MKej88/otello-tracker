from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from life360_market_data import build_yahoo_chart_url, parse_yahoo_chart  # noqa: E402


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


def test_yahoo_chart_url_requests_bounded_daily_history() -> None:
    url = build_yahoo_chart_url("360.AX", "2019-05-10", "2019-05-31")
    assert "/360.AX?" in url
    assert "interval=1d" in url
    assert "events=history" in url
    assert "includeAdjustedClose=false" in url


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
