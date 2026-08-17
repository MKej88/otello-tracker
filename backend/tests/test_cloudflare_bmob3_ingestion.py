from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from bmob3_ingestion import (  # noqa: E402
    B3_TZ,
    download_bmob3_web_quote,
    finalize_bmob3_eod_price,
    parse_bmob3_web_quote,
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


class FakeRepository:
    def __init__(self, *, eod_done: bool = False) -> None:
        self.eod_done = eod_done
        self.documents: list[dict] = []
        self.prices: list[dict] = []

    async def first(self, sql: str, parameters=()):
        if "bmob3-eod-last-check" in str(parameters):
            return {"ok": 1} if self.eod_done else None
        return None

    async def create_source_document(self, **kwargs):
        self.documents.append(kwargs)
        return 301

    async def upsert_market_price(self, **kwargs):
        self.prices.append(kwargs)
        return 302


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.ok = True
        self.status = 200
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
    repository = FakeRepository()

    async def fake_fetch(url: str, **kwargs):
        return FakeResponse(payload)

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
