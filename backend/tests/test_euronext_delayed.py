import csv
import io
import zipfile
from decimal import Decimal

import pytest

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.marketdata.euronext_delayed import (
    OTEC_ISIN,
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
        row = connection.execute(
            """
            SELECT mp.price_type, mp.price, mp.currency, mp.quality, mp.metadata_json,
                   mp.observed_at, mp.trading_date, s.code AS source_code,
                   sd.document_type, sd.url
            FROM market_prices mp
            JOIN sources s ON s.id = mp.source_id
            JOIN source_documents sd ON sd.id = mp.source_document_id
            JOIN instruments i ON i.id = mp.instrument_id
            WHERE i.symbol = 'OTEC' AND mp.price_type = 'LAST'
            """
        ).fetchone()
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


def test_refresh_uses_previous_day_only_when_current_has_no_otec(tmp_path, monkeypatch) -> None:
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
