from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from otec_activity import (  # noqa: E402
    PREVIOUS_DAY_SELECTION,
    ingest_otec_daily_activity,
    refresh_otec_daily_activity,
)
from otec_ingestion import OTEC_ISIN  # noqa: E402

HEADER = (
    "TradingDateTime,PublicationDateTime,MifidInstrumentID,MifidPrice,"
    "MifidQuantity,MifidPriceNotation,MifidCurrency,Venue,"
    "TradeUniqueIdentifier,MissingPrice,VenueOfPublication\n"
)


def _zip_payload(rows: list[str]) -> bytes:
    csv_text = "Euronext delayed-data notice\n" + HEADER + "".join(rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("delayed.csv", csv_text)
    return buffer.getvalue()


def _row(*, day: str, time: str, price: str, quantity: str, trade_id: str) -> str:
    return (
        f"{day}T{time}Z,{day}T15:30:00Z,{OTEC_ISIN},{price},{quantity},MONE,NOK,XOSL,"
        f"{trade_id},,XOSL\n"
    )


class FakeRepository:
    def __init__(self, *, official_dates: set[str] | None = None, fallback_dates: set[str] | None = None):
        self.official_dates = set(official_dates or set())
        self.fallback_dates = set(fallback_dates or set())
        self.documents: list[dict] = []
        self.runs: list[tuple[str, tuple]] = []

    async def first(self, sql: str, parameters=()):
        if "s.code='EURONEXT'" in sql and "market_activity" in sql:
            return {"ok": 1} if str(parameters[0]) in self.official_dates else None
        if "SELECT id FROM sources WHERE code='FT_MARKETS'" in sql:
            return {"id": 77}
        if "FROM market_activity" in sql and "source_id=?" in sql:
            return {"ok": 1} if str(parameters[1]) in self.fallback_dates else None
        return None

    async def create_source_document(self, **kwargs):
        self.documents.append(kwargs)
        return 101

    async def instrument_id(self, symbol: str):
        assert symbol == "OTEC"
        return 11

    async def source_id(self, code: str):
        assert code == "EURONEXT"
        return 7

    async def run(self, sql: str, parameters=()):
        self.runs.append((sql, tuple(parameters)))
        if "INSERT INTO market_activity" in sql:
            self.official_dates.add(str(parameters[1]))
        if "DELETE FROM market_activity" in sql:
            self.fallback_dates.discard(str(parameters[1]))
        return None


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.ok = True
        self.status = 200
        self.headers = {"content-length": str(len(payload))}

    async def arrayBuffer(self):
        return self.payload


def test_daily_activity_aggregates_exact_euronext_session_and_replaces_fallback() -> None:
    payload = _zip_payload(
        [
            _row(day="2026-08-21", time="10:00:00", price="17.00", quantity="30000", trade_id="a"),
            _row(day="2026-08-21", time="14:00:00", price="17.04", quantity="46185", trade_id="b"),
            _row(day="2026-08-20", time="14:00:00", price="17.00", quantity="999", trade_id="old"),
        ]
    )
    repository = FakeRepository(fallback_dates={"2026-08-21"})

    result = asyncio.run(
        ingest_otec_daily_activity(
            repository,
            payload,
            selection=PREVIOUS_DAY_SELECTION,
            source_url="https://example.test/euronext",
            target_date="2026-08-21",
        )
    )

    assert result["status"] == "ok"
    assert result["volume_shares"] == 76185
    assert result["last_price_nok"] == "17.04"
    assert result["trade_rows"] == 2
    assert result["replaced_secondary_fallback"] is True
    assert "2026-08-21" in repository.official_dates
    assert "2026-08-21" not in repository.fallback_dates
    insert = next(item for item in repository.runs if "INSERT INTO market_activity" in item[0])
    assert insert[1][2] == 76185
    metadata = json.loads(insert[1][6])
    assert metadata["source_quality"] == "OFFICIAL_DELAYED_TRADE_FILE"
    assert metadata["aggregation"].startswith("sum MifidQuantity")


def test_refresh_repairs_previous_trading_day_once_without_refetching() -> None:
    payload = _zip_payload(
        [
            _row(day="2026-08-26", time="10:00:00", price="17.00", quantity="10000", trade_id="a"),
            _row(day="2026-08-26", time="14:00:00", price="17.12", quantity="20000", trade_id="b"),
        ]
    )
    repository = FakeRepository()
    requested: list[str] = []

    async def fetcher(url: str, **kwargs):
        requested.append(url)
        return FakeResponse(payload)

    now = datetime(2026, 8, 27, 9, 30, tzinfo=ZoneInfo("Europe/Oslo"))
    first = asyncio.run(refresh_otec_daily_activity(repository, now=now, fetcher=fetcher))
    second = asyncio.run(refresh_otec_daily_activity(repository, now=now, fetcher=fetcher))

    assert first["written"] == 1
    assert first["attempts"][0]["target_date"] == "2026-08-26"
    assert second["written"] == 0
    assert second["attempts"][0]["reason"] == "previous_day_already_stored"
    assert len(requested) == 1
    assert "PREVIOUS_TRADING_DAY" in requested[0]
