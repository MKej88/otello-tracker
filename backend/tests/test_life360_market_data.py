from __future__ import annotations

import asyncio
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import life360_ir_lseg  # noqa: E402
import life360_market_data  # noqa: E402
from life360_market_data import (  # noqa: E402
    LIFE360_CONTROL_SYMBOLS,
    LIFE360_REQUIRED_SYMBOL,
    YAHOO_QUERY1_BASE,
    YAHOO_QUERY2_BASE,
    _download_chart_with_host_fallback,
    build_yahoo_chart_url,
    parse_yahoo_chart,
    refresh_life360_market_data,
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
    assert url.startswith(f"{YAHOO_QUERY1_BASE}/360.AX?")
    assert "interval=1d" in url
    assert "events=history" in url
    assert "includeAdjustedClose=false" in url


def test_public_yahoo_url_builder_does_not_accept_an_origin() -> None:
    assert "base_url" not in inspect.signature(build_yahoo_chart_url).parameters
    assert "endpoint" not in inspect.signature(build_yahoo_chart_url).parameters
    with pytest.raises(ValueError, match="Ikke tillatt Yahoo-symbol"):
        build_yahoo_chart_url("https://evil.example", "2026-08-20", "2026-08-24")


def test_yahoo_chart_download_falls_back_to_second_endpoint() -> None:
    calls: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        calls.append(url)
        if url.startswith(YAHOO_QUERY1_BASE):
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
    assert calls[0].startswith(YAHOO_QUERY1_BASE)
    assert calls[1].startswith(YAHOO_QUERY2_BASE)
    assert url.startswith(YAHOO_QUERY2_BASE)
    assert provider == YAHOO_QUERY2_BASE
    assert payload == _payload()


def test_lif_is_required_while_asx_is_control_series() -> None:
    assert LIFE360_REQUIRED_SYMBOL == "LIF"
    assert LIFE360_CONTROL_SYMBOLS == {"360.AX"}


def test_required_lif_uses_independent_ir_fallback_when_both_yahoo_hosts_fail(monkeypatch) -> None:
    async def fake_refresh_symbol(repository, *, symbol, target_date, archive_bucket, fetcher):
        if symbol == "LIF":
            raise RuntimeError(
                "Yahoo Finance chart feilet på alle endepunkter: query1: HTTP 503; query2: HTTP 503"
            )
        raise RuntimeError("ASX control unavailable")

    async def fake_ir_fallback(repository, *, target_date, archive_bucket=None, fetcher=None):
        return {
            "status": "ok",
            "symbol": "LIF",
            "source_code": "LIFE360_IR_LSEG",
            "provider": "LSEG via Life360 Investor Relations",
            "price_date": target_date,
            "price": "45.25",
            "rows_written": 1,
            "fallback_only": True,
            "history_backfill": False,
            "history_complete": False,
        }

    monkeypatch.setattr(life360_market_data, "_refresh_symbol", fake_refresh_symbol)
    monkeypatch.setattr(life360_ir_lseg, "refresh_life360_ir_lif", fake_ir_fallback)

    result = asyncio.run(
        refresh_life360_market_data(
            object(),
            target_date="2026-08-25",
        )
    )

    assert result["status"] == "ok"
    assert result["fallback_used"] is True
    assert result["provider"] == "Life360 IR/LSEG"
    assert result["rows_written"] == 1
    assert result["series"]["LIF"]["fallback_from"] == "YAHOO_FINANCE"
    assert result["series"]["LIF"]["source_code"] == "LIFE360_IR_LSEG"
    assert result["control_status"] == "degraded"
    assert result["control_errors"][0]["symbol"] == "360.AX"
    assert result["errors"] == []


def test_ir_fallback_does_not_hide_non_transport_errors(monkeypatch) -> None:
    fallback_called = False

    async def fake_refresh_symbol(repository, *, symbol, target_date, archive_bucket, fetcher):
        if symbol == "LIF":
            raise RuntimeError("D1 write failed")
        return {"status": "ok", "symbol": symbol, "rows_written": 0}

    async def fake_ir_fallback(repository, *, target_date, archive_bucket=None, fetcher=None):
        nonlocal fallback_called
        fallback_called = True
        return {"status": "ok"}

    monkeypatch.setattr(life360_market_data, "_refresh_symbol", fake_refresh_symbol)
    monkeypatch.setattr(life360_ir_lseg, "refresh_life360_ir_lif", fake_ir_fallback)

    result = asyncio.run(refresh_life360_market_data(object(), target_date="2026-08-25"))

    assert result["status"] == "error"
    assert fallback_called is False
    assert result["errors"][0]["symbol"] == "LIF"


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


def test_d1_price_writes_never_exceed_bound_parameter_limit() -> None:
    class RecordingRepository:
        def __init__(self) -> None:
            self.parameter_counts: list[int] = []

        async def source_id(self, source_code: str) -> int:
            assert source_code == "YAHOO_FINANCE"
            return 7

        async def instrument_id(self, symbol: str) -> int:
            assert symbol == "LIF"
            return 9

        async def run(self, sql: str, parameters=()):
            assert "INSERT INTO market_prices" in sql
            self.parameter_counts.append(len(parameters))

    repository = RecordingRepository()
    rows = [
        {
            "observed_at": f"2026-08-{day:02d}T20:00:00Z",
            "trading_date": f"2026-08-{day:02d}",
            "price": f"{44 + day / 100:.2f}",
        }
        for day in range(1, 26)
    ]

    written = asyncio.run(
        life360_market_data._write_rows(
            repository,
            symbol="LIF",
            currency="USD",
            rows=rows,
            document_id=42,
            role="NASDAQ_COMMON",
        )
    )

    assert life360_market_data.BOUND_PARAMETERS_PER_ROW == 8
    assert life360_market_data.WRITE_BATCH_ROWS == 12
    assert (
        life360_market_data.WRITE_BATCH_ROWS * life360_market_data.BOUND_PARAMETERS_PER_ROW
        <= life360_market_data.D1_MAX_BOUND_PARAMETERS
    )
    assert written == 25
    assert repository.parameter_counts == [96, 96, 8]
    assert max(repository.parameter_counts) <= life360_market_data.D1_MAX_BOUND_PARAMETERS


def test_yahoo_repair_window_covers_one_month_history() -> None:
    assert life360_market_data.RECENT_LOOKBACK_DAYS == 45
