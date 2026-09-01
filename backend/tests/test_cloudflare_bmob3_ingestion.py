from __future__ import annotations

import asyncio
import json
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import b3_full_refresh  # noqa: E402
from bmob3_ingestion import (  # noqa: E402
    B3_TZ,
    bmob3_eod_check_done,
    download_bmob3_web_quote,
    finalize_bmob3_eod_price,
    parse_bmob3_web_quote,
    parse_bmob3_yahoo_quote,
    refresh_bmob3_intraday_price,
)


def _payload(*, provider_time: str = "2026-08-17 14:30:00", price: str = "23.45") -> bytes:
    data = {
        "BizSts": {"cd": "OK"},
        "Msg": {"dtTm": provider_time},
        "Trad": [
            {
                "ttlQty": 4321,
                "scty": {
                    "symb": "BMOB3",
                    "desc": "BEMOBI ON",
                    "mkt": {"nm": "CASH"},
                    "SctyQtn": {
                        "curPrc": price,
                        "opngPric": "23.00",
                        "minPric": "22.90",
                        "maxPric": "23.60",
                        "avrgPric": "23.30",
                        "prcFlcn": "1.25",
                    },
                },
            }
        ],
    }
    return json.dumps(data).encode("utf-8")


def _yahoo_payload(
    *,
    timestamp: int = 1787074200,
    price: float = 24.15,
    symbol: str = "BMOB3.SA",
    currency: str = "BRL",
    timezone_name: str | None = "America/Sao_Paulo",
    volume: int | None = 187_654,
    minute_volumes: tuple[int, int] = (80_000, 107_654),
) -> bytes:
    meta = {
        "symbol": symbol,
        "currency": currency,
        "exchangeTimezoneName": timezone_name,
        "regularMarketPrice": price,
        "regularMarketTime": timestamp,
    }
    if volume is not None:
        meta["regularMarketVolume"] = volume
    data = {
        "chart": {
            "result": [
                {
                    "meta": meta,
                    "timestamp": [timestamp - 60, timestamp],
                    "indicators": {
                        "quote": [
                            {
                                "close": [price - 0.05, price],
                                "volume": list(minute_volumes),
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    return json.dumps(data).encode("utf-8")


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


class FakeRepository:
    def __init__(self, *, eod_done: bool = False, official_close_done: bool = False) -> None:
        self.eod_done = eod_done
        self.official_close_done = official_close_done
        self.documents: list[dict] = []
        self.prices: list[dict] = []

    async def first(self, sql: str, parameters=()):
        if "bmob3-eod-last-check" in str(parameters):
            return {"ok": 1} if self.eod_done else None
        if "mp.price_type='CLOSE'" in sql and self.official_close_done:
            return {"ok": 1}
        return None

    async def create_source_document(self, **kwargs):
        self.documents.append(kwargs)
        return 301

    async def upsert_market_price(self, **kwargs):
        self.prices.append(kwargs)
        return 302


class FakeResponse:
    def __init__(self, payload: bytes = b"", *, status: int = 200) -> None:
        self.payload = payload
        self.ok = 200 <= status < 300
        self.status = status
        self.headers = {"content-length": str(len(payload))}

    async def text(self):
        return self.payload.decode("utf-8")


def test_bmob3_parser_preserves_15_minute_effective_timestamp() -> None:
    quote = parse_bmob3_web_quote(_payload())

    assert quote.symbol == "BMOB3"
    assert str(quote.price) == "23.45"
    assert quote.trading_date == "2026-08-17"
    assert quote.provider_at == "2026-08-17T17:30:00Z"
    assert quote.observed_at == "2026-08-17T17:15:00Z"
    assert quote.total_trades == 4321


def test_yahoo_parser_requires_bmob3_brl_and_uses_latest_timestamped_close() -> None:
    quote = parse_bmob3_yahoo_quote(_yahoo_payload())

    assert str(quote.price) == "24.15"
    assert quote.trading_date == "2026-08-18"
    assert quote.observed_at == "2026-08-18T17:30:00Z"
    assert quote.volume_shares == 187_654
    assert quote.volume_basis == "YAHOO_REGULAR_MARKET_VOLUME"

    with pytest.raises(ValueError, match="symbol"):
        parse_bmob3_yahoo_quote(_yahoo_payload(symbol="WRONG.SA"))
    with pytest.raises(ValueError, match="valuta"):
        parse_bmob3_yahoo_quote(_yahoo_payload(currency="USD"))


def test_yahoo_parser_sums_minute_volume_when_regular_market_volume_is_missing() -> None:
    quote = parse_bmob3_yahoo_quote(
        _yahoo_payload(volume=None, minute_volumes=(12_345, 67_890))
    )

    assert quote.volume_shares == 80_235
    assert quote.volume_basis == "YAHOO_1M_VOLUME_SUM"


def test_yahoo_parser_uses_latest_valid_close_and_only_volume_through_that_time() -> None:
    payload = json.loads(_yahoo_payload(volume=None))
    result = payload["chart"]["result"][0]
    result["timestamp"] = [1787074140, 1787074200, 1787074260]
    result["indicators"]["quote"][0] = {
        "close": [24.10, 24.15, None],
        "volume": [10_000, 20_000, 30_000],
    }

    quote = parse_bmob3_yahoo_quote(json.dumps(payload))

    assert str(quote.price) == "24.15"
    assert quote.provider_at == "2026-08-18T17:30:00Z"
    assert quote.volume_shares == 30_000
    assert quote.volume_basis == "YAHOO_1M_VOLUME_SUM"


@pytest.mark.parametrize("timezone_name", [None, "UTC", "Ugyldig/Tidssone"])
def test_yahoo_parser_rejects_missing_or_wrong_bmob3_timezone(
    timezone_name: str | None,
) -> None:
    with pytest.raises(ValueError, match="exchangeTimezoneName"):
        parse_bmob3_yahoo_quote(_yahoo_payload(timezone_name=timezone_name))


def test_worker_fetch_does_not_send_forbidden_connection_header() -> None:
    captured: dict = {}

    async def fake_fetch(url: str, **kwargs):
        captured.update(kwargs)
        return FakeResponse(_payload())

    url, payload = asyncio.run(download_bmob3_web_quote(fetcher=fake_fetch))

    assert url.endswith("/BMOB3")
    assert payload
    assert "Connection" not in captured["headers"]
    assert captured["headers"]["Accept"] == "application/json"


def test_bmob3_intraday_worker_write_matches_reference_semantics() -> None:
    payload = _payload()
    yahoo_payload = _yahoo_payload(timestamp=1786988700, volume=155_000)
    repository = FakeRepository()
    calls: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        calls.append(url)
        host = _host(url)
        if host == "cotacao.b3.com.br":
            return FakeResponse(payload)
        if host == "query1.finance.yahoo.com":
            return FakeResponse(yahoo_payload)
        raise AssertionError(f"unexpected host: {host}")

    result = asyncio.run(
        refresh_bmob3_intraday_price(
            repository=repository,
            now=datetime(2026, 8, 17, 14, 45, tzinfo=B3_TZ),
            fetcher=fake_fetch,
        )
    )

    assert result["status"] == "ok"
    assert result["price_type"] == "LAST"
    assert result["quality"] == "DIRECT"
    assert result["price_brl"] == "23.45"
    assert result["volume_shares"] == 155_000
    assert result["volume_source"] == "YAHOO_FINANCE"
    assert len(calls) == 2
    assert _host(calls[0]) == "cotacao.b3.com.br"
    assert _host(calls[1]) == "query1.finance.yahoo.com"
    assert len(repository.documents) == 1
    assert len(repository.prices) == 1
    document = repository.documents[0]
    price = repository.prices[0]
    assert document["source_code"] == "B3"
    assert document["external_id"].startswith("bmob3-web-quote-")
    assert price["symbol"] == "BMOB3"
    assert price["currency"] == "BRL"
    assert price["price_type"] == "LAST"
    assert price["quality"] == "DIRECT"
    assert price["metadata"]["public_delay_minutes"] == 15
    assert price["metadata"]["payload_policy"] == "BOUNDED_JSON_RESPONSE"
    assert price["metadata"]["volume_shares"] == 155_000
    assert price["metadata"]["volume_source"] == "YAHOO_FINANCE"
    assert price["metadata"]["volume_provisional"] is True


def test_bmob3_intraday_http_526_uses_same_day_yahoo_fallback() -> None:
    repository = FakeRepository()
    yahoo_payload = _yahoo_payload()
    calls: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        calls.append(url)
        host = _host(url)
        if host == "cotacao.b3.com.br":
            return FakeResponse(status=526)
        if host == "query1.finance.yahoo.com":
            return FakeResponse(yahoo_payload)
        raise AssertionError(f"unexpected host: {host}")

    result = asyncio.run(
        refresh_bmob3_intraday_price(
            repository=repository,
            now=datetime(2026, 8, 18, 14, 45, tzinfo=B3_TZ),
            fetcher=fake_fetch,
        )
    )

    assert result["status"] == "ok"
    assert result["feed_mode"] == "yahoo_intraday_fallback"
    assert result["quality"] == "DIRECT"
    assert result["price_brl"] == "24.15"
    assert result["trading_date"] == "2026-08-18"
    assert result["volume_shares"] == 187_654
    assert result["volume_source"] == "YAHOO_FINANCE"
    assert "HTTP 526" in result["fallback_reason"]
    assert len(calls) == 2
    assert repository.documents[0]["source_code"] == "YAHOO_FINANCE"
    assert repository.prices[0]["source_code"] == "YAHOO_FINANCE"
    assert repository.prices[0]["quality"] == "DIRECT"
    assert repository.prices[0]["metadata"]["fallback_only"] is True
    assert repository.prices[0]["metadata"]["source_policy"] == "UNOFFICIAL_SECONDARY_FALLBACK"
    assert repository.prices[0]["metadata"]["volume_shares"] == 187_654
    assert repository.prices[0]["metadata"]["volume_provisional"] is True


def test_bmob3_intraday_yahoo_query2_is_used_when_query1_fails() -> None:
    repository = FakeRepository()
    yahoo_payload = _yahoo_payload()
    calls: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        calls.append(url)
        host = _host(url)
        if host == "cotacao.b3.com.br":
            return FakeResponse(status=526)
        if host == "query1.finance.yahoo.com":
            return FakeResponse(status=503)
        if host == "query2.finance.yahoo.com":
            return FakeResponse(yahoo_payload)
        raise AssertionError(f"unexpected host: {host}")

    result = asyncio.run(
        refresh_bmob3_intraday_price(
            repository=repository,
            now=datetime(2026, 8, 18, 14, 45, tzinfo=B3_TZ),
            fetcher=fake_fetch,
        )
    )

    assert result["status"] == "ok"
    assert _host(result["provider_endpoint"]) == "query2.finance.yahoo.com"
    assert len(calls) == 3


def test_bmob3_intraday_rejects_stale_yahoo_fallback() -> None:
    repository = FakeRepository()
    stale = _yahoo_payload(timestamp=1786987800)

    async def fake_fetch(url: str, **kwargs):
        if _host(url) == "cotacao.b3.com.br":
            return FakeResponse(status=526)
        return FakeResponse(stale)

    with pytest.raises(RuntimeError, match="Yahoo fallback var stale"):
        asyncio.run(
            refresh_bmob3_intraday_price(
                repository=repository,
                now=datetime(2026, 8, 18, 14, 45, tzinfo=B3_TZ),
                fetcher=fake_fetch,
            )
        )
    assert not repository.documents
    assert not repository.prices


def test_bmob3_eod_is_idempotent_and_not_mislabeled_as_official_close() -> None:
    payload = _payload(provider_time="2026-08-17 19:30:00", price="23.70")

    async def fake_fetch(url: str, **kwargs):
        return FakeResponse(payload)

    repository = FakeRepository()
    result = asyncio.run(
        finalize_bmob3_eod_price(
            repository,
            target_date="2026-08-17",
            fetcher=fake_fetch,
        )
    )

    assert result["status"] == "ok"
    assert result["price_type"] == "LAST"
    assert repository.documents[0]["external_id"] == "bmob3-eod-last-check-2026-08-17"
    assert repository.prices[0]["metadata"]["price_semantics"] == (
        "FINAL_DELAYED_WEB_QUOTE_NOT_COTAHIST_CLOSE"
    )

    already_done = FakeRepository(eod_done=True)
    skipped = asyncio.run(
        finalize_bmob3_eod_price(
            already_done,
            target_date="2026-08-17",
            fetcher=fake_fetch,
        )
    )
    assert skipped == {
        "status": "skipped",
        "reason": "eod_already_finalized",
        "target_date": "2026-08-17",
    }
    assert not already_done.documents
    assert not already_done.prices


def test_official_b3_close_also_counts_as_eod_finalized() -> None:
    repository = FakeRepository(official_close_done=True)
    assert asyncio.run(bmob3_eod_check_done(repository, "2026-08-17")) is True


def test_eod_quote_http_failure_falls_back_to_exact_official_cotahist(monkeypatch) -> None:
    repository = FakeRepository()
    calls: list[dict] = []

    async def fake_fetch(url: str, **kwargs):
        return FakeResponse(status=526)

    async def fake_official_close(repository_arg, *, target_date, max_lookback_days, fetcher=None, **kwargs):
        calls.append(
            {
                "repository": repository_arg,
                "target_date": target_date,
                "max_lookback_days": max_lookback_days,
                "fetcher": fetcher,
            }
        )
        return {
            "status": "ok",
            "trading_date": target_date,
            "price_brl": "23.70",
            "price_id": 701,
            "source_document_id": 702,
            "attempted_dates": [target_date],
        }

    monkeypatch.setattr(b3_full_refresh, "refresh_bmob3_close", fake_official_close)
    result = asyncio.run(
        finalize_bmob3_eod_price(
            repository,
            target_date="2026-08-17",
            fetcher=fake_fetch,
        )
    )

    assert result["status"] == "ok"
    assert result["feed_mode"] == "official_cotahist_fallback"
    assert result["price_type"] == "CLOSE"
    assert result["price_brl"] == "23.70"
    assert "HTTP 526" in result["fallback_reason"]
    assert len(calls) == 1
    assert calls[0]["target_date"] == "2026-08-17"
    assert calls[0]["max_lookback_days"] == 0


def test_bmob3_intraday_skips_outside_market_window_without_network() -> None:
    called = False

    async def fake_fetch(url: str, **kwargs):
        nonlocal called
        called = True
        return FakeResponse(_payload())

    repository = FakeRepository()
    result = asyncio.run(
        refresh_bmob3_intraday_price(
            repository=repository,
            now=datetime(2026, 8, 17, 9, 30, tzinfo=ZoneInfo("America/Sao_Paulo")),
            fetcher=fake_fetch,
        )
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "before_b3_quote_window"
    assert called is False
