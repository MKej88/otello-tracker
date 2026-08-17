import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import app.marketdata.bmob3_feed as feed
from app.db.connection import get_connection
from app.db.migration_runner import init_database


B3_TZ = ZoneInfo("America/Sao_Paulo")


def _payload(*, timestamp="2026-08-17 11:45:03", price=22.59, symbol="BMOB3") -> bytes:
    return json.dumps(
        {
            "BizSts": {"cd": "OK"},
            "Msg": {"dtTm": timestamp},
            "Trad": [
                {
                    "scty": {
                        "SctyQtn": {
                            "opngPric": 22.67,
                            "minPric": 22.49,
                            "maxPric": 22.69,
                            "avrgPric": 22.582,
                            "curPrc": price,
                            "prcFlcn": -0.2727335,
                        },
                        "mkt": {"nm": "Vista"},
                        "symb": symbol,
                        "desc": "BEMOBI TECH ON EJ NM",
                    },
                    "ttlQty": 291,
                }
            ],
        }
    ).encode()


def test_parse_bmob3_quote_tracks_provider_and_15_minute_effective_time() -> None:
    quote = feed.parse_bmob3_web_quote(_payload())
    assert quote.symbol == "BMOB3"
    assert quote.price == Decimal("22.59")
    assert quote.trading_date == "2026-08-17"
    assert quote.provider_at == "2026-08-17T14:45:03Z"
    assert quote.observed_at == "2026-08-17T14:30:03Z"
    assert quote.total_trades == 291


def test_parse_rejects_wrong_symbol_and_invalid_price() -> None:
    try:
        feed.parse_bmob3_web_quote(_payload(symbol="OTHER3"))
    except ValueError as exc:
        assert "BMOB3" in str(exc)
    else:
        raise AssertionError("wrong symbol should fail")

    try:
        feed.parse_bmob3_web_quote(_payload(price=0))
    except ValueError as exc:
        assert "curPrc" in str(exc)
    else:
        raise AssertionError("zero price should fail")


def test_intraday_refresh_persists_delayed_last(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "bmob3.db")
    init_database(database)
    payload = _payload()
    monkeypatch.setattr(
        feed,
        "download_bmob3_web_quote",
        lambda **_kwargs: ("https://cotacao.b3.com.br/example", payload),
    )

    result = feed.refresh_bmob3_intraday_price(
        database,
        now=datetime(2026, 8, 17, 12, 0, tzinfo=B3_TZ),
    )
    assert result["status"] == "ok"
    assert result["price_type"] == "LAST"
    assert result["price_brl"] == "22.59"
    assert result["observed_at"] == "2026-08-17T14:30:03Z"
    assert result["provider_at"] == "2026-08-17T14:45:03Z"
    assert result["delay_minutes"] == 15

    with get_connection(database) as connection:
        row = connection.execute(
            """
            SELECT mp.price_type, mp.price, mp.quality, mp.observed_at, mp.metadata_json
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            WHERE i.symbol='BMOB3' AND mp.trading_date='2026-08-17'
            ORDER BY mp.id DESC LIMIT 1
            """
        ).fetchone()
    assert row["price_type"] == "LAST"
    assert Decimal(row["price"]) == Decimal("22.59")
    assert row["quality"] == "DIRECT"
    assert row["observed_at"] == "2026-08-17T14:30:03Z"
    assert '"public_delay_minutes": 15' in row["metadata_json"]


def test_intraday_skips_before_window_and_after_eod(monkeypatch) -> None:
    monkeypatch.setattr(
        feed,
        "download_bmob3_web_quote",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network not expected")),
    )
    before = feed.refresh_bmob3_intraday_price(
        "unused.db",
        now=datetime(2026, 8, 17, 10, 14, tzinfo=B3_TZ),
    )
    after = feed.refresh_bmob3_intraday_price(
        "unused.db",
        now=datetime(2026, 8, 17, 19, 15, tzinfo=B3_TZ),
    )
    assert before["reason"] == "before_b3_quote_window"
    assert after["reason"] == "eod_window_has_priority"


def test_ash_wednesday_uses_special_start(monkeypatch) -> None:
    monkeypatch.setattr(
        feed,
        "download_bmob3_web_quote",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network not expected")),
    )
    result = feed.refresh_bmob3_intraday_price(
        "unused.db",
        now=datetime(2026, 2, 18, 13, 14, tzinfo=B3_TZ),
    )
    assert result["reason"] == "before_b3_quote_window"


def test_eod_finalization_stores_last_not_close(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "bmob3-eod.db")
    init_database(database)
    payload = _payload(timestamp="2026-08-17 19:20:00", price=22.61)
    monkeypatch.setattr(
        feed,
        "download_bmob3_web_quote",
        lambda **_kwargs: ("https://cotacao.b3.com.br/example", payload),
    )

    first = feed.finalize_bmob3_eod_price(database, target_date="2026-08-17")
    second = feed.finalize_bmob3_eod_price(database, target_date="2026-08-17")

    assert first["status"] == "ok"
    assert first["price_type"] == "LAST"
    assert first["observed_at"] == "2026-08-17T22:05:00Z"
    assert second == {
        "status": "skipped",
        "reason": "eod_already_finalized",
        "target_date": "2026-08-17",
    }

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT mp.price_type, mp.price, mp.metadata_json
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            WHERE i.symbol='BMOB3' AND mp.trading_date='2026-08-17'
            """
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["price_type"] == "LAST"
    assert Decimal(rows[0]["price"]) == Decimal("22.61")
    assert "FINAL_DELAYED_WEB_QUOTE_NOT_COTAHIST_CLOSE" in rows[0]["metadata_json"]
