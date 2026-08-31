import csv
import io
import zipfile
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import app.marketdata.otec_feed as feed
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.marketdata.euronext_delayed import OTEC_ISIN


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


def test_intraday_feed_uses_small_windows_and_skips_full_file_with_recent_poll(
    tmp_path, monkeypatch
) -> None:
    database = str(tmp_path / "recent.db")
    init_database(database)
    oslo = ZoneInfo("Europe/Oslo")
    now = datetime(2026, 8, 17, 12, 0, tzinfo=oslo)
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO job_runs(job_name, started_at, finished_at, status, metadata_json)
            VALUES ('fast_refresh', ?, ?, 'SUCCESS', '{}')
            """,
            ("2026-08-17T09:29:00+00:00", "2026-08-17T09:30:00+00:00"),
        )
        connection.commit()

    captured = {}

    def fake_refresh(database_path=None, *, selections, timeout):
        captured["database_path"] = database_path
        captured["selections"] = selections
        captured["timeout"] = timeout
        return {"status": "no_trade", "selected": None, "attempts": []}

    monkeypatch.setattr(feed, "refresh_otec_delayed_price", fake_refresh)
    monkeypatch.setattr(
        feed,
        "download_euronext_delayed_equities",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full file not expected")),
    )

    result = feed.refresh_otec_intraday_price(database, now=now)

    assert captured["database_path"] == database
    assert captured["selections"] == ("LAST_15_MINUTES", "LAST_HOUR")
    assert captured["timeout"] == 45
    assert result["feed_mode"] == "delayed_intraday"
    assert result["status"] == "no_trade"
    assert result["gap_recovery"] is False
    assert result["gap_recovery_skipped"] == "recent_poll_covered_by_last_hour"


def test_intraday_cold_start_recovers_trade_outside_last_hour(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "cold-start.db")
    init_database(database)
    oslo = ZoneInfo("Europe/Oslo")
    now = datetime(2026, 8, 17, 14, 0, tzinfo=oslo)
    calls = []

    monkeypatch.setattr(
        feed,
        "refresh_otec_delayed_price",
        lambda *_args, **_kwargs: {"status": "no_trade", "selected": None, "attempts": []},
    )

    def fake_download(selection, *, timeout=120, attempts=3):
        calls.append((selection, timeout))
        return "https://example/current-day", b"current-day-payload"

    def fake_import(payload, *, time_selection, source_url, database_path):
        assert payload == b"current-day-payload"
        assert time_selection == "CURRENT_TRADING_DAY"
        assert source_url == "https://example/current-day"
        assert database_path == database
        return {
            "found": True,
            "price_nok": "17.15",
            "trading_date": "2026-08-17",
        }

    monkeypatch.setattr(feed, "download_euronext_delayed_equities", fake_download)
    monkeypatch.setattr(feed, "import_delayed_otec_trade", fake_import)

    result = feed.refresh_otec_intraday_price(database, now=now)

    assert calls == [("CURRENT_TRADING_DAY", 120)]
    assert result["gap_recovery"] is True
    assert result["status"] == "ok"
    assert result["selected"] == "CURRENT_TRADING_DAY"
    assert result["price_nok"] == "17.15"


def test_intraday_partial_poll_does_not_hide_a_gap(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "partial-poll.db")
    init_database(database)
    oslo = ZoneInfo("Europe/Oslo")
    now = datetime(2026, 8, 17, 14, 0, tzinfo=oslo)
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO job_runs(job_name, started_at, finished_at, status, metadata_json)
            VALUES ('fast_refresh', ?, ?, 'PARTIAL', '{}')
            """,
            ("2026-08-17T11:29:00+00:00", "2026-08-17T11:30:00+00:00"),
        )
        connection.commit()

    monkeypatch.setattr(
        feed,
        "refresh_otec_delayed_price",
        lambda *_args, **_kwargs: {
            "status": "no_trade",
            "selected": None,
            "attempts": [],
        },
    )
    monkeypatch.setattr(
        feed,
        "download_euronext_delayed_equities",
        lambda *_args, **_kwargs: (
            "https://example/current-day",
            b"current-day-payload",
        ),
    )
    monkeypatch.setattr(
        feed,
        "import_delayed_otec_trade",
        lambda *_args, **_kwargs: {
            "found": True,
            "price_nok": "17.15",
            "trading_date": "2026-08-17",
        },
    )

    result = feed.refresh_otec_intraday_price(database, now=now)

    assert result["gap_recovery"] is True
    assert result["selected"] == "CURRENT_TRADING_DAY"
    assert result["price_nok"] == "17.15"


def test_intraday_small_window_trade_never_uses_full_file(monkeypatch) -> None:
    oslo = ZoneInfo("Europe/Oslo")
    monkeypatch.setattr(
        feed,
        "refresh_otec_delayed_price",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "found": True,
            "selected": "LAST_15_MINUTES",
            "price_nok": "17.20",
        },
    )
    monkeypatch.setattr(
        feed,
        "download_euronext_delayed_equities",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full file not expected")),
    )

    result = feed.refresh_otec_intraday_price(
        "unused.db",
        now=datetime(2026, 8, 17, 14, 0, tzinfo=oslo),
    )
    assert result["gap_recovery"] is False
    assert result["selected"] == "LAST_15_MINUTES"


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
    assert result["quality"] == "DIRECT"
    assert result["price_semantics"] == "EOD_LAST_TRADE"
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
    assert rows[0]["quality"] == "DIRECT"
    assert '"feed_mode": "EOD_LAST_TRADE"' in rows[0]["metadata_json"]
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
