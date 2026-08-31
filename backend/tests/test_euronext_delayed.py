import csv
import io
import zipfile
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.marketdata.euronext_delayed import (
    OTEC_ISIN,
    download_euronext_delayed_equities,
    import_delayed_otec_trade,
    latest_otec_trade,
    parse_euronext_delayed_trades,
    refresh_otec_delayed_price,
)

HEADER = [
    "TradingDateTime",
    "PublicationDateTime",
    "MifidInstrumentID",
    "MifidPrice",
    "MifidQuantity",
    "MifidPriceNotation",
    "MifidCurrency",
    "MmtMarketMechanism",
    "MmtNegotiationIndicator",
    "MmtModificationIndicator",
    "MmtBenchMarkIndicator",
    "MmtContributionToPrice",
    "MmtAlgorithmicIndicator",
    "MmtPublicationMode",
    "Venue",
    "ThirdCountryTradingVenueExecution",
    "TradeUniqueIdentifier",
    "MissingPrice",
    "MmtContingentTransactionIndicator",
    "VenueOfPublication",
]


def _row(**overrides):
    row = {
        "TradingDateTime": "2026-08-17T07:48:29.123456Z",
        "PublicationDateTime": "2026-08-17T07:48:30.123456Z",
        "MifidInstrumentID": OTEC_ISIN,
        "MifidPrice": "17.2000000",
        "MifidQuantity": "100.0",
        "MifidPriceNotation": "MONE",
        "MifidCurrency": "NOK",
        "MmtMarketMechanism": "1",
        "MmtNegotiationIndicator": "-",
        "MmtModificationIndicator": "-",
        "MmtBenchMarkIndicator": "-",
        "MmtContributionToPrice": "-",
        "MmtAlgorithmicIndicator": "-",
        "MmtPublicationMode": "-",
        "Venue": "XOSL",
        "ThirdCountryTradingVenueExecution": "",
        "TradeUniqueIdentifier": "OTEC-1",
        "MissingPrice": "",
        "MmtContingentTransactionIndicator": "-",
        "VenueOfPublication": "XOSL",
    }
    row.update(overrides)
    return row


def _zip(rows, *, header=HEADER, terms=True):
    text = io.StringIO()
    if terms:
        text.write("(c) 2025 Euronext N.V. All Rights Reserved. delayed-data terms\n")
    writer = csv.DictWriter(
        text,
        fieldnames=header,
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Trades_Equities.csv", text.getvalue().encode("utf-8"))
    return buffer.getvalue()


def test_parser_filters_exact_otec_isin_and_picks_latest_trade() -> None:
    payload = _zip(
        [
            _row(
                TradingDateTime="2026-08-17T07:40:00.000000Z",
                PublicationDateTime="2026-08-17T07:40:01.000000Z",
                MifidPrice="17.1000000",
                TradeUniqueIdentifier="OTEC-OLD",
            ),
            _row(
                MifidInstrumentID="NO0000000000",
                MifidPrice="999.0000000",
                TradeUniqueIdentifier="OTHER",
            ),
            _row(
                TradingDateTime="2026-08-17T07:48:29.123456Z",
                PublicationDateTime="2026-08-17T07:48:30.123456Z",
                MifidPrice="17.2300000",
                MifidQuantity="321.0",
                TradeUniqueIdentifier="OTEC-LATEST",
            ),
            _row(
                TradingDateTime="2026-08-17T07:50:00.000000Z",
                PublicationDateTime="2026-08-17T07:50:01.000000Z",
                MifidPrice="999.0000000",
                MifidCurrency="SEK",
                TradeUniqueIdentifier="WRONG-CURRENCY",
            ),
        ]
    )
    trades = parse_euronext_delayed_trades(payload)
    assert len(trades) == 2
    latest = latest_otec_trade(payload)
    assert latest is not None
    assert latest.trade_unique_identifier == "OTEC-LATEST"
    assert latest.price == Decimal("17.2300000")
    assert latest.quantity == Decimal("321.0")
    assert latest.trading_datetime == "2026-08-17T07:48:29.123456Z"


def test_parser_fails_on_missing_required_header() -> None:
    payload = _zip([_row()], header=[name for name in HEADER if name != "MifidPrice"])
    with pytest.raises(ValueError, match="header"):
        parse_euronext_delayed_trades(payload)


def test_parser_rejects_publication_before_trade() -> None:
    payload = _zip(
        [
            _row(
                TradingDateTime="2026-08-17T08:00:00.000000Z",
                PublicationDateTime="2026-08-17T07:59:59.000000Z",
            )
        ]
    )
    with pytest.raises(ValueError, match="før TradingDateTime"):
        parse_euronext_delayed_trades(payload)


def test_latest_trade_compares_instants_across_timezone_boundary() -> None:
    """The newest trade must be chosen by instant, not timestamp text or local date."""
    payload = _zip(
        [
            _row(
                TradingDateTime="2026-08-18T00:05:00+02:00",
                PublicationDateTime="2026-08-18T00:05:01+02:00",
                MifidPrice="17.1000000",
                TradeUniqueIdentifier="LOCAL-NEXT-DAY",
            ),
            _row(
                TradingDateTime="2026-08-17T22:10:00Z",
                PublicationDateTime="2026-08-17T22:10:01Z",
                MifidPrice="17.3000000",
                TradeUniqueIdentifier="ACTUALLY-LATEST",
            ),
        ]
    )

    latest = latest_otec_trade(payload)

    assert latest is not None
    assert latest.trade_unique_identifier == "ACTUALLY-LATEST"
    assert latest.price == Decimal("17.3000000")
    assert latest.trading_date == "2026-08-17"


def test_parser_rejects_partial_otec_row_without_trading_timestamp() -> None:
    """A partial API row must fail closed instead of becoming a misleading price."""
    payload = _zip([_row(TradingDateTime="")])

    with pytest.raises(ValueError, match="mangler TradingDateTime"):
        parse_euronext_delayed_trades(payload)


def test_download_respects_retry_after_on_rate_limit(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []
    expected = _zip([_row()])

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return expected

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(
                "https://example.test",
                429,
                "Too Many Requests",
                {"Retry-After": "7"},
                None,
            )
        return Response()

    monkeypatch.setattr(
        "app.marketdata.euronext_delayed.urllib.request.urlopen", fake_urlopen
    )
    monkeypatch.setattr("app.marketdata.euronext_delayed.time.sleep", sleeps.append)

    _, payload = download_euronext_delayed_equities(
        "CURRENT_TRADING_DAY", timeout=1, attempts=2
    )

    assert payload == expected
    assert calls == 2
    assert sleeps == [7.0]


def test_download_does_not_retry_permanent_http_error(monkeypatch) -> None:
    calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError("https://example.test", 404, "Not Found", {}, None)

    monkeypatch.setattr(
        "app.marketdata.euronext_delayed.urllib.request.urlopen", fake_urlopen
    )

    with pytest.raises(RuntimeError, match="HTTP 404"):
        download_euronext_delayed_equities("CURRENT_TRADING_DAY", timeout=1, attempts=3)

    assert calls == 1


def test_import_stores_direct_last_trade_with_audit_metadata(tmp_path) -> None:
    database = str(tmp_path / "euronext-delayed.db")
    init_database(database)
    payload = _zip([_row(MifidPrice="17.2345000", TradeUniqueIdentifier="OTEC-AUDIT")])
    result = import_delayed_otec_trade(
        payload,
        time_selection="CURRENT_TRADING_DAY",
        source_url="https://marketdata.euronext.com/example",
        database_path=database,
    )
    assert result["found"] is True
    assert result["price_nok"] == "17.2345000"

    with get_connection(database) as connection:
        row = connection.execute("""
            SELECT mp.price_type, mp.price, mp.currency, mp.quality, mp.metadata_json,
                   mp.observed_at, mp.trading_date, s.code AS source_code,
                   sd.document_type, sd.url
            FROM market_prices mp
            JOIN sources s ON s.id = mp.source_id
            JOIN source_documents sd ON sd.id = mp.source_document_id
            JOIN instruments i ON i.id = mp.instrument_id
            WHERE i.symbol = 'OTEC' AND mp.price_type = 'LAST'
            """).fetchone()
        assert row["price_type"] == "LAST"
        assert Decimal(row["price"]) == Decimal("17.2345000")
        assert row["currency"] == "NOK"
        assert row["quality"] == "DIRECT"
        assert row["source_code"] == "EURONEXT"
        assert row["document_type"] == "DELAYED_MARKET_DATA_FILE"
        assert row["observed_at"] == "2026-08-17T07:48:29.123456Z"
        assert row["trading_date"] == "2026-08-17"
        assert "DELAYED_PUBLIC_TRADE_FILE" in row["metadata_json"]
        assert "OTEC-AUDIT" in row["metadata_json"]


def test_reimporting_identical_trade_is_idempotent(tmp_path) -> None:
    """A retry of the same payload must not duplicate price or audit records."""
    database = str(tmp_path / "euronext-idempotent.db")
    init_database(database)
    payload = _zip([_row(TradeUniqueIdentifier="OTEC-RETRY")])

    first = import_delayed_otec_trade(
        payload,
        time_selection="CURRENT_TRADING_DAY",
        source_url="https://example.test/current",
        database_path=database,
    )
    second = import_delayed_otec_trade(
        payload,
        time_selection="CURRENT_TRADING_DAY",
        source_url="https://example.test/current",
        database_path=database,
    )

    assert second["price_id"] == first["price_id"]
    with get_connection(database) as connection:
        price_count = connection.execute(
            "SELECT COUNT(*) FROM market_prices WHERE price_type = 'LAST'"
        ).fetchone()[0]
        document_count = connection.execute(
            "SELECT COUNT(*) FROM source_documents "
            "WHERE document_type = 'DELAYED_MARKET_DATA_FILE'"
        ).fetchone()[0]
    assert price_count == 1
    assert document_count == 1


def test_refresh_uses_previous_day_only_when_current_has_no_otec(
    tmp_path, monkeypatch
) -> None:
    database = str(tmp_path / "euronext-fallback.db")
    init_database(database)
    current = _zip([_row(MifidInstrumentID="NO0000000000")])
    previous = _zip(
        [
            _row(
                TradingDateTime="2026-08-14T14:24:00.000000Z",
                PublicationDateTime="2026-08-14T14:24:01.000000Z",
                MifidPrice="17.2000000",
                TradeUniqueIdentifier="OTEC-PREVIOUS",
            )
        ]
    )
    calls = []

    def fake_download(selection, timeout=120, attempts=3):
        calls.append(selection)
        payload = current if selection == "CURRENT_TRADING_DAY" else previous
        return f"https://example/{selection}", payload

    monkeypatch.setattr(
        "app.marketdata.euronext_delayed.download_euronext_delayed_equities",
        fake_download,
    )
    result = refresh_otec_delayed_price(database)
    assert calls == ["CURRENT_TRADING_DAY", "PREVIOUS_TRADING_DAY"]
    assert result["status"] == "ok"
    assert result["selected"] == "PREVIOUS_TRADING_DAY"
    assert result["trading_date"] == "2026-08-14"
    assert result["price_nok"] == "17.2000000"
