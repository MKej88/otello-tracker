from __future__ import annotations

import asyncio
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from otec_ingestion import (  # noqa: E402
    OTEC_ISIN,
    import_delayed_otec_trade,
    latest_otec_trade,
    refresh_otec_intraday,
)

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


def _otec_row(
    *,
    trade_time: str,
    publication_time: str,
    price: str,
    quantity: str,
    trade_id: str,
    isin: str = OTEC_ISIN,
) -> str:
    return (
        f"{trade_time},{publication_time},{isin},{price},{quantity},MONE,NOK,XOSL,"
        f"{trade_id},,XOSL\n"
    )


class FakeRepository:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.prices: list[dict] = []

    async def create_source_document(self, **kwargs):
        self.documents.append(kwargs)
        return 101

    async def upsert_market_price(self, **kwargs):
        self.prices.append(kwargs)
        return 202


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.ok = True
        self.status = 200
        self.headers = {"content-length": str(len(payload))}

    async def arrayBuffer(self):
        return self.payload


def test_streamed_euronext_parser_selects_latest_valid_otec_trade() -> None:
    payload = _zip_payload(
        [
            _otec_row(
                trade_time="2026-08-17T10:00:00Z",
                publication_time="2026-08-17T10:15:00Z",
                price="17.10",
                quantity="100",
                trade_id="older",
            ),
            _otec_row(
                trade_time="2026-08-17T10:05:00Z",
                publication_time="2026-08-17T10:20:00Z",
                price="17.25",
                quantity="200",
                trade_id="newer",
            ),
            _otec_row(
                trade_time="2026-08-17T10:06:00Z",
                publication_time="2026-08-17T10:21:00Z",
                price="99.00",
                quantity="1",
                trade_id="other",
                isin="NO0000000000",
            ),
        ]
    )

    latest = latest_otec_trade(payload)

    assert latest is not None
    assert latest.trade_unique_identifier == "newer"
    assert str(latest.price) == "17.25"
    assert latest.trading_datetime == "2026-08-17T10:05:00.000000Z"


def test_worker_import_preserves_reference_provenance_and_direct_last_semantics() -> None:
    payload = _zip_payload(
        [
            _otec_row(
                trade_time="2026-08-17T10:05:00Z",
                publication_time="2026-08-17T10:20:00Z",
                price="17.25",
                quantity="200",
                trade_id="trade-1",
            )
        ]
    )
    repository = FakeRepository()

    result = asyncio.run(
        import_delayed_otec_trade(
            repository,
            payload,
            time_selection="LAST_15_MINUTES",
            source_url="https://example.test/euronext",
        )
    )

    assert result["found"] is True
    assert result["price_id"] == 202
    assert len(repository.documents) == 1
    assert len(repository.prices) == 1
    document = repository.documents[0]
    price = repository.prices[0]
    assert document["source_code"] == "EURONEXT"
    assert document["external_id"].startswith("otec-delayed-last_15_minutes-2026-08-17-")
    assert price["symbol"] == "OTEC"
    assert price["price_type"] == "LAST"
    assert price["quality"] == "DIRECT"
    assert price["price"] == "17.25"
    assert price["source_document_id"] == 101
    assert price["metadata"]["price_semantics"] == "LATEST_REPORTED_TRADE_NOT_OFFICIAL_CLOSE"
    assert price["metadata"]["payload_policy"] == "BOUNDED_ROLLING_WINDOW_STREAMED_ZIP_MEMBER"


def test_intraday_refresh_falls_back_from_15_minutes_to_last_hour() -> None:
    no_otec = _zip_payload(
        [
            _otec_row(
                trade_time="2026-08-17T10:00:00Z",
                publication_time="2026-08-17T10:15:00Z",
                price="50.00",
                quantity="10",
                trade_id="other",
                isin="NO0000000000",
            )
        ]
    )
    last_hour = _zip_payload(
        [
            _otec_row(
                trade_time="2026-08-17T09:45:00Z",
                publication_time="2026-08-17T10:00:00Z",
                price="17.00",
                quantity="300",
                trade_id="hour-trade",
            )
        ]
    )
    requested: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        requested.append(url)
        if "LAST_15_MINUTES" in url:
            return FakeResponse(no_otec)
        if "LAST_HOUR" in url:
            return FakeResponse(last_hour)
        raise AssertionError(url)

    repository = FakeRepository()
    result = asyncio.run(refresh_otec_intraday(repository=repository, fetcher=fake_fetch))

    assert result["status"] == "ok"
    assert result["selected"] == "LAST_HOUR"
    assert result["trade_unique_identifier"] == "hour-trade"
    assert len(requested) == 2
    assert len(repository.prices) == 1
