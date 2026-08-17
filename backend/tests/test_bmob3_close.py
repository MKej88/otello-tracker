from datetime import date
from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import app.marketdata.bmob3_close as close
from app.db.connection import get_connection
from app.db.migration_runner import init_database


def _put(chars: list[str], start: int, end: int, value: str) -> None:
    chars[start:end] = list(value.ljust(end - start)[: end - start])


def _line(trading_day: date, close_cents: int = 2251) -> str:
    chars = list(" " * 245)
    _put(chars, 0, 2, "01")
    _put(chars, 2, 10, trading_day.strftime("%Y%m%d"))
    _put(chars, 10, 12, "02")
    _put(chars, 12, 24, "BMOB3")
    _put(chars, 24, 27, "010")
    _put(chars, 52, 56, "R$")
    _put(chars, 108, 121, f"{close_cents:013d}")
    _put(chars, 147, 152, "00291")
    _put(chars, 170, 188, f"{123456700:018d}")
    _put(chars, 210, 217, "0000001")
    _put(chars, 230, 242, "BRBMOBACNOR1")
    return "".join(chars)


def _zip(trading_day: date, close_cents: int = 2251) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            f"COTAHIST_D{trading_day.strftime('%d%m%Y')}.TXT",
            "00HEADER\n" + _line(trading_day, close_cents) + "\n99TRAILER\n",
        )
    return output.getvalue()


def test_daily_close_payload_persists_official_close(tmp_path) -> None:
    database = str(tmp_path / "close.db")
    init_database(database)
    trading_day = date(2026, 8, 14)

    result = close.import_bmob3_daily_close_payload(
        _zip(trading_day, 2251),
        trading_day=trading_day,
        database_path=database,
    )

    assert result["status"] == "ok"
    assert result["price_type"] == "CLOSE"
    assert result["quality"] == "DIRECT"
    assert result["price_brl"] == "22.51"

    with get_connection(database) as connection:
        row = connection.execute(
            """
            SELECT mp.price_type, mp.price, mp.quality, mp.metadata_json
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            WHERE i.symbol='BMOB3' AND mp.trading_date='2026-08-14'
            ORDER BY mp.id DESC LIMIT 1
            """
        ).fetchone()
    assert row["price_type"] == "CLOSE"
    assert Decimal(row["price"]) == Decimal("22.51")
    assert row["quality"] == "DIRECT"
    assert "OFFICIAL_DAILY_CLOSE" in row["metadata_json"]


def test_live_close_refresh_falls_back_to_previous_b3_session(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "fallback.db")
    init_database(database)
    monday = date(2026, 8, 17)
    friday = date(2026, 8, 14)
    calls = []

    def fake_download(day):
        calls.append(day)
        if day == monday:
            return None
        if day == friday:
            return _zip(friday, 2248)
        raise AssertionError(day)

    monkeypatch.setattr(close, "download_cotahist_day", fake_download)
    result = close.refresh_bmob3_official_close(database, target_date=monday.isoformat())

    assert calls == [monday, friday]
    assert result["status"] == "ok"
    assert result["trading_date"] == "2026-08-14"
    assert result["price_brl"] == "22.48"
    assert result["attempted"] == [
        {"trading_date": "2026-08-17", "available": False},
        {"trading_date": "2026-08-14", "available": True},
    ]


def test_existing_previous_close_avoids_redownload_after_current_404(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "existing.db")
    init_database(database)
    monday = date(2026, 8, 17)
    friday = date(2026, 8, 14)
    close.import_bmob3_daily_close_payload(
        _zip(friday, 2248),
        trading_day=friday,
        database_path=database,
    )
    calls = []

    def fake_download(day):
        calls.append(day)
        assert day == monday
        return None

    monkeypatch.setattr(close, "download_cotahist_day", fake_download)
    result = close.refresh_bmob3_official_close(database, target_date=monday.isoformat())

    assert calls == [monday]
    assert result["status"] == "skipped"
    assert result["reason"] == "official_close_already_present"
    assert result["trading_date"] == "2026-08-14"
