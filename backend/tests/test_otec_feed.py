import csv
import io
import zipfile
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.marketdata.euronext_delayed import OTEC_ISIN
import app.marketdata.otec_feed as feed


HEADER = [
    "TradingDateTime",
    "PublicationDateTime",
    "MifidInstrumentID",
    "MifidPrice",
    "MifidQuantity",
    "MifidPriceNotation",
    "MifidCurrency",
    "Venue",
    "TradeUniqueIdentifier",
    "MissingPrice",
    "VenueOfPublication",
]


def _row(**overrides):
    row = {
        "TradingDateTime": "2026-08-17T14:20:00.000000Z",
        "PublicationDateTime": "2026-08-17T14:20:01.000000Z",
        "MifidInstrumentID": OTEC_ISIN,
        "MifidPrice": "17.2000000",
        "MifidQuantity": "100",
        "MifidPriceNotation": "MONE",
        "MifidCurrency": "NOK",
        "Venue": "XOSL",
        "TradeUniqueIdentifier": "OTEC-1",
        "MissingPrice": "",
        "VenueOfPublication": "XOSL",
    }
    row.update(overrides)
    return row


def _zip(rows):
    text = io.StringIO()
    text.write("(c) Euronext delayed-data terms\n")
    writer = csv.DictWriter(text, fieldnames=HEADER, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Trades_Equities.csv", text.getvalue().encode("utf-8"))
    return buffer.getvalue()


def test_intraday_feed_uses_small_delayed_windows(monkeypatch) -> None:
    captured = {}

    def fake_refresh(database_path=None, *, selections, timeout):
        captured["database_path"] = database_path
        captured["selections"] = selections
        captured["timeout"] = timeout
        return {"status": "no_trade", "selected": None, "attempts": []}

    monkeypatch.setattr(feed, "refresh_otec_delayed_price", fake_refresh)
    result = feed.refresh_otec_intraday_price("example.db")

    assert captured["database_path"] == "example.db"
    assert captured["selections"] == ("LAST_15_MINUTES", "LAST_HOUR")
    assert captured["timeout"] == 45
    assert result["feed_mode"] == "delayed_intraday"
    assert result["status"] == "no_trade"


def test_eod_finalization_stores_last_not_close(tmp_path) -> None:
    database = str(tmp_path / "eod.db")
    init_database(database)
    payload = _zip(
        [
            _row(
                TradingDateTime="2026-08-17T14:18:00.000000Z",
                PublicationDateTime="2026-08-17T14:18:01.000000Z",
                MifidPrice="17.1800000",
                TradeUniqueIdentifier="OTEC-EARLY",
            ),
            _row(
                TradingDateTime="2026-08-17T14:24:59.000000Z",
                PublicationDateTime="2026-08-17T14:25:01.000000Z",
                MifidPrice="17.2300000",
                MifidQuantity="250",
                TradeUniqueIdentifier="OTEC-FINAL",
            ),
        ]
    )

    result = feed.finalize_otec_eod_from_payload(
        payload,
        source_url="https://marketdata.euronext.com/example",
        target_date="2026-08-17",
        database_path=database,
        source_selection="CURRENT_TRADING_DAY",
    )

    assert result["status"] == "ok"
    assert result["price_type"] == "LAST"
    assert result["quality"] == "EOD_LAST_TRADE"
    assert Decimal(result["price_nok"]) == Decimal("17.23")
    assert feed.eod_otec_check_done(database, "2026-08-17") is True

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT mp.price_type, mp.price, mp.quality, mp.metadata_json
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            WHERE i.symbol='OTEC' AND mp.trading_date='2026-08-17'
            """
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["price_type"] == "LAST"
    assert rows[0]["quality"] == "EOD_LAST_TRADE"
    assert "FINAL_REPORTED_TRADE_NOT_OFFICIAL_CLOSE" in rows[0]["metadata_json"]


def test_eod_no_trade_is_marked_checked_to_prevent_repeat_download(tmp_path) -> None:
    database = str(tmp_path / "no-trade.db")
    init_database(database)
    payload = _zip([_row(MifidInstrumentID="NO0000000000")])

    result = feed.finalize_otec_eod_from_payload(
        payload,
        source_url="https://marketdata.euronext.com/example",
        target_date="2026-08-17",
        database_path=database,
        source_selection="CURRENT_TRADING_DAY",
    )

    assert result["status"] == "no_trade"
    assert feed.eod_otec_check_done(database, "2026-08-17") is True


def test_eod_cutoff_prevents_heavy_day_file_before_1645(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        feed,
        "finalize_otec_eod_price",
        lambda *_args, **_kwargs: called.append(True) or {"status": "ok"},
    )
    oslo = ZoneInfo("Europe/Oslo")

    before = feed.maybe_finalize_otec_eod(
        "example.db",
        target_date="2026-08-17",
        now=datetime(2026, 8, 17, 16, 44, tzinfo=oslo),
    )
    after = feed.maybe_finalize_otec_eod(
        "example.db",
        target_date="2026-08-17",
        now=datetime(2026, 8, 17, 16, 45, tzinfo=oslo),
    )

    assert before["status"] == "skipped"
    assert before["reason"] == "before_eod_cutoff"
    assert after["status"] == "ok"
    assert called == [True]
