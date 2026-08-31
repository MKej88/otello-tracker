from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from otec_ingestion import (  # noqa: E402
    MAX_RECOVERY_ZIP_BYTES,
    OTEC_ISIN,
    download_euronext_recovery,
    import_delayed_otec_trade,
    latest_otec_trade,
    maybe_finalize_otec_eod,
    refresh_otec_intraday,
    refresh_otec_with_gap_recovery,
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
    def __init__(
        self,
        *,
        job_rows: list[dict] | None = None,
        latest_price: dict | None = None,
        eod_done: bool = False,
    ) -> None:
        self.job_rows = job_rows or []
        self.latest_price = latest_price
        self.eod_done = eod_done
        self.documents: list[dict] = []
        self.prices: list[dict] = []

    async def all(self, sql: str, parameters=()):
        if "FROM job_runs" in sql:
            return list(self.job_rows)
        return []

    async def first(self, sql: str, parameters=()):
        if "FROM source_documents" in sql and "otec-eod-last-check" in str(parameters):
            return {"ok": 1} if self.eod_done else None
        if "FROM market_prices" in sql and "i.symbol='OTEC'" in sql:
            return self.latest_price
        return None

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
        self.array_buffer_called = False

    async def arrayBuffer(self):
        self.array_buffer_called = True
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


@pytest.mark.parametrize(
    ("price", "quantity"),
    [("Infinity", "100"), ("17.25", "Infinity")],
)
def test_streamed_euronext_parser_rejects_non_finite_numbers(
    price: str, quantity: str
) -> None:
    payload = _zip_payload(
        [
            _otec_row(
                trade_time="2026-08-17T10:05:00Z",
                publication_time="2026-08-17T10:20:00Z",
                price=price,
                quantity=quantity,
                trade_id="invalid-number",
            )
        ]
    )

    with pytest.raises(ValueError, match="Ugyldig ikke-positiv OTEC-pris"):
        latest_otec_trade(payload)


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


def test_gap_recovery_skips_day_file_when_recent_otec_poll_has_overlap_coverage() -> None:
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
    requested: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        requested.append(url)
        return FakeResponse(no_otec)

    repository = FakeRepository(
        job_rows=[
            {
                "finished_at": "2026-08-17T11:30:00Z",
                "metadata_json": json.dumps(
                    {"steps": {"otec_delayed": {"status": "no_trade"}}}
                ),
            }
        ]
    )
    result = asyncio.run(
        refresh_otec_with_gap_recovery(
            repository=repository,
            now=datetime(2026, 8, 17, 14, 0, tzinfo=ZoneInfo("Europe/Oslo")),
            fetcher=fake_fetch,
        )
    )

    assert result["status"] == "no_trade"
    assert result["gap_recovery"] is False
    assert result["gap_recovery_skipped"] == "recent_poll_covered_by_last_hour"
    assert len(requested) == 2
    assert all("CURRENT_TRADING_DAY" not in url for url in requested)


def test_gap_recovery_uses_bounded_current_day_file_after_poll_gap() -> None:
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
    day_file = _zip_payload(
        [
            _otec_row(
                trade_time="2026-08-17T10:20:00Z",
                publication_time="2026-08-17T10:35:00Z",
                price="17.35",
                quantity="250",
                trade_id="recovered",
            )
        ]
    )
    requested: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        requested.append(url)
        if "CURRENT_TRADING_DAY" in url:
            return FakeResponse(day_file)
        return FakeResponse(no_otec)

    repository = FakeRepository(
        job_rows=[
            {
                "finished_at": "2026-08-17T09:00:00Z",
                "metadata_json": json.dumps(
                    {"steps": {"otec_delayed": {"status": "no_trade"}}}
                ),
            }
        ]
    )
    result = asyncio.run(
        refresh_otec_with_gap_recovery(
            repository=repository,
            now=datetime(2026, 8, 17, 14, 0, tzinfo=ZoneInfo("Europe/Oslo")),
            fetcher=fake_fetch,
        )
    )

    assert result["status"] == "ok"
    assert result["gap_recovery"] is True
    assert result["selected"] == "CURRENT_TRADING_DAY"
    assert result["trade_unique_identifier"] == "recovered"
    assert len(requested) == 3
    assert "CURRENT_TRADING_DAY" in requested[-1]
    assert repository.prices[-1]["metadata"]["feed_mode"] == "WORKER_GAP_RECOVERY"
    assert repository.prices[-1]["metadata"]["payload_policy"] == (
        "BOUNDED_FULL_DAY_ZIP_STREAMED_CSV_MEMBER"
    )


def test_recovery_rejects_oversized_payload_before_buffering_body() -> None:
    response = FakeResponse(b"not-used")
    response.headers = {"content-length": str(MAX_RECOVERY_ZIP_BYTES + 1)}

    async def fake_fetch(url: str, **kwargs):
        return response

    try:
        asyncio.run(download_euronext_recovery(fetcher=fake_fetch))
    except ValueError as exc:
        assert "recovery-ZIP overstiger Worker-grensen" in str(exc)
    else:
        raise AssertionError("Forventet at oversized recovery-fil ble avvist")

    assert response.array_buffer_called is False


def test_eod_finalizes_latest_stored_trade_from_rolling_coverage_without_day_file() -> None:
    repository = FakeRepository(
        latest_price={
            "id": 77,
            "observed_at": "2026-08-17T14:25:00.000000Z",
            "price": "17.40",
            "currency": "NOK",
            "source_document_id": 55,
            "metadata_json": json.dumps(
                {"publication_datetime": "2026-08-17T14:40:00.000000Z"}
            ),
        }
    )
    result = asyncio.run(
        maybe_finalize_otec_eod(
            repository=repository,
            now=datetime(2026, 8, 17, 17, 0, tzinfo=ZoneInfo("Europe/Oslo")),
            current_refresh={
                "status": "no_trade",
                "selected": None,
                "gap_recovery": False,
            },
        )
    )

    assert result["status"] == "ok"
    assert result["price_type"] == "LAST"
    assert result["quality"] == "DIRECT"
    assert result["price_nok"] == "17.40"
    assert result["finalization_method"] == "rolling_window_coverage"
    assert len(repository.documents) == 1
    assert repository.documents[0]["external_id"] == "otec-eod-last-check-2026-08-17"
    assert len(repository.prices) == 1
    assert repository.prices[0]["source_document_id"] == 101
    assert repository.prices[0]["metadata"]["price_semantics"] == (
        "FINAL_REPORTED_TRADE_NOT_OFFICIAL_CLOSE"
    )
    assert repository.prices[0]["metadata"]["original_source_document_id"] == 55
