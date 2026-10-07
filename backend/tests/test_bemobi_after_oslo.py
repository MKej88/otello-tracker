from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloudflare/src"))
import bemobi_after_oslo as feature  # noqa: E402
import bmob3_ingestion as feed  # noqa: E402


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Repository:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE runtime_state(key TEXT PRIMARY KEY,value TEXT,updated_at TEXT);
            CREATE TABLE instruments(id INTEGER PRIMARY KEY,symbol TEXT);
            CREATE TABLE sources(id INTEGER PRIMARY KEY,code TEXT);
            CREATE TABLE market_prices(id INTEGER PRIMARY KEY,instrument_id INTEGER,
              source_id INTEGER,price TEXT,observed_at TEXT,trading_date TEXT,
              price_type TEXT,metadata_json TEXT);
            CREATE TABLE market_activity(id INTEGER PRIMARY KEY,instrument_id INTEGER,source_id INTEGER,trading_date TEXT,last_price_nok TEXT,metadata_json TEXT);
            CREATE TABLE fx_rates(id INTEGER PRIMARY KEY,base_currency TEXT,quote_currency TEXT,
              rate TEXT,observed_at TEXT,source_id INTEGER);
            CREATE TABLE bemobi_holdings(id INTEGER PRIMARY KEY,shares INTEGER,
              effective_from TEXT,effective_to TEXT);
            CREATE TABLE otello_share_counts(id INTEGER PRIMARY KEY,outstanding_shares INTEGER,
              effective_from TEXT,effective_to TEXT);
            INSERT INTO instruments VALUES(1,'BMOB3'),(2,'OTEC');
            INSERT INTO sources VALUES(1,'B3'),(2,'YAHOO_FINANCE');
        """)

    async def all(self, sql, parameters=()):
        return [dict(row) for row in self.db.execute(sql, parameters).fetchall()]

    async def first(self, sql, parameters=()):
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None

    async def run(self, sql, parameters=()):
        self.db.execute(sql, parameters)

    def anchor(self, day="2026-10-05", price="20", observed="2026-10-05T14:25:00Z"):
        anchor = {
            "price": price,
            "observed_at": observed,
            "oslo_close_at": feature.iso(feature.closing_auction(dt(day).date())),
            "source": "B3",
            "approximate": True,
        }
        self.db.execute(
            "INSERT INTO runtime_state VALUES(?,?,?)",
            (feature.STATE_PREFIX + day, json.dumps(anchor), observed),
        )

    def quote(self, at, price, source=1, price_type="LAST"):
        self.db.execute(
            "INSERT INTO market_prices(instrument_id,source_id,price,observed_at,trading_date,price_type,metadata_json) VALUES(1,?,?,?,?,?,?)",
            (
                source,
                str(price),
                at,
                at[:10],
                price_type,
                json.dumps({"public_delay_minutes": 15}),
            ),
        )


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-10-05T14:24:59Z", "2026-10-02T14:25:00Z"),
        ("2026-10-05T14:25:00Z", "2026-10-05T14:25:00Z"),
        ("2026-10-06T07:00:00Z", "2026-10-05T14:25:00Z"),
        ("2026-10-10T10:00:00Z", "2026-10-09T14:25:00Z"),
        ("2026-11-02T15:30:00Z", "2026-11-02T15:25:00Z"),
        ("2026-04-01T11:10:00Z", "2026-04-01T11:05:00Z"),
        ("2026-04-02T16:00:00Z", "2026-04-01T11:05:00Z"),
    ],
)
def test_reference_session_calendar_and_dst(now, expected):
    assert feature.iso(feature.latest_oslo_close(dt(now))) == expected


@pytest.mark.parametrize(
    ("now", "valid"),
    [
        ("2026-10-05T14:40:00Z", True),
        ("2026-10-05T14:42:30Z", True),
        ("2026-10-05T15:40:00Z", False),
        ("2026-11-02T15:40:00Z", True),
        ("2026-11-02T14:40:00Z", False),
        ("2026-04-01T11:20:00Z", True),
        ("2026-10-04T14:40:00Z", False),
    ],
)
def test_capture_schedule_filters_other_dst_hour_and_holidays(now, valid):
    assert (feature.capture_window(dt(now)) is not None) is valid


@pytest.mark.parametrize(("price", "expected"), [(20.4, 2), (19.6, -2), (20, 0)])
def test_change_and_chart_from_frozen_reference(price, expected):
    repo = Repository()
    repo.anchor()
    repo.quote("2026-10-05T14:45:00Z", price)
    result = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-05T15:00:00Z"))
    )
    assert result["ready"]
    assert result["change_pct"] == pytest.approx(expected)
    assert result["points"][0]["change_pct"] == 0
    assert result["points"][-1]["change_pct"] == pytest.approx(expected)
    assert result["latest"]["delay_minutes"] == 15


def test_missing_reference_never_substitutes_old_half_hour_quote():
    repo = Repository()
    repo.quote("2026-10-05T14:15:00Z", 20)
    repo.quote("2026-10-05T14:45:00Z", 21)
    waiting = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-05T14:35:00Z"))
    )
    missing = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-05T15:00:00Z"))
    )
    assert waiting["status"] == "waiting_reference"
    assert missing["status"] == "missing_reference"
    assert "change_pct" not in missing


def test_future_quotes_daily_closes_and_invalid_numbers_are_not_used():
    repo = Repository()
    repo.anchor()
    repo.quote("2026-10-05T14:45:00Z", "NaN")
    repo.quote("2026-10-05T14:45:00Z", -2)
    repo.quote("2026-10-05T14:45:00Z", 100, price_type="CLOSE")
    repo.quote("2026-10-05T15:30:00Z", 200)
    result = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-05T15:00:00Z"))
    )
    assert result["status"] == "waiting_quote"
    assert "change_pct" not in result


def test_latest_timestamp_wins_but_b3_wins_equal_time():
    repo = Repository()
    repo.anchor()
    repo.quote("2026-10-05T14:45:00Z", 20.2)
    repo.quote("2026-10-05T14:50:00Z", 20.4, source=2)
    result = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-05T15:00:00Z"))
    )
    assert result["latest"]["source"] == "YAHOO_FINANCE"
    repo.quote("2026-10-05T14:50:00Z", 20.3)
    result = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-05T15:00:00Z"))
    )
    assert result["latest"]["source"] == "B3"
    assert len(result["points"]) == 3


def test_overnight_reference_is_retained_but_new_close_requires_new_reference():
    repo = Repository()
    repo.anchor()
    repo.quote("2026-10-05T22:00:00Z", 20.4)
    morning = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-06T07:00:00Z"))
    )
    assert morning["ready"]
    assert morning["reference"]["price"] == 20
    after_close = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-06T14:35:00Z"))
    )
    assert after_close["status"] == "waiting_reference"


def test_stale_intraday_quote_suppresses_change():
    repo = Repository()
    repo.anchor()
    repo.quote("2026-10-05T14:45:00Z", 20.4)
    result = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-05T17:00:00Z"))
    )
    assert result["status"] == "stale_quote"
    assert "change_pct" not in result


def test_early_afternoon_quote_remains_stale_overnight():
    repo = Repository()
    repo.anchor()
    repo.quote("2026-10-05T14:45:00Z", 20.4)
    result = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-06T07:00:00Z"))
    )
    assert result["status"] == "stale_quote"
    assert "change_pct" not in result


def test_capture_delay_validation_and_immutability(monkeypatch):
    repo = Repository()
    quote = feed.Bmob3WebQuote(
        symbol="BMOB3",
        price=feed.Decimal("20"),
        provider_datetime=dt("2026-10-05T14:40:00Z"),
        open_price=None,
        min_price=None,
        max_price=None,
        average_price=None,
        price_change_pct=None,
        total_trades=None,
        description=None,
        market_name=None,
    )
    fetches = []

    async def download(**_kwargs):
        fetches.append(1)
        return "https://cotacao.b3.com.br", b"{}"

    async def persist(*_args, **_kwargs):
        return 7

    monkeypatch.setattr(feed, "download_bmob3_web_quote", download)
    monkeypatch.setattr(feed, "parse_bmob3_web_quote", lambda _: quote)
    monkeypatch.setattr(feed, "_persist_quote", persist)
    first = asyncio.run(feature.capture_reference(repo, now=dt("2026-10-05T14:40:02Z")))
    second = asyncio.run(
        feature.capture_reference(repo, now=dt("2026-10-05T14:41:00Z"))
    )
    assert first["reference"]["observed_at"] == "2026-10-05T14:25:00Z"
    assert first["reference"]["price_id"] == 7
    assert second["reason"] == "reference_already_captured"
    assert len(fetches) == 1
    bad_repo = Repository()
    bad = asyncio.run(
        feature.capture_reference(bad_repo, now=dt("2026-10-05T14:42:00Z"))
    )
    assert bad["status"] == "missing"  # stale provider response clock
    assert not bad_repo.db.execute("SELECT * FROM runtime_state").fetchall()


def test_database_failure_is_not_disguised_as_missing_reference():
    repo = Repository()
    repo.db.close()
    with pytest.raises(sqlite3.ProgrammingError):
        asyncio.run(feature.bemobi_after_oslo(repo, now=datetime.now(UTC)))


def effect_repo():
    repo = Repository()
    repo.anchor()
    repo.db.executescript("""
        INSERT INTO sources VALUES(3,'EURONEXT'),(4,'NORGES_BANK');
        INSERT INTO market_prices VALUES(10,2,3,'20','2026-10-05T14:25:00Z','2026-10-05','CLOSE','{}');
        INSERT INTO fx_rates VALUES(1,'BRL','NOK','2','2026-10-05T12:00:00Z',4);
        INSERT INTO bemobi_holdings VALUES(1,100,'2026-01-01',NULL);
        INSERT INTO otello_share_counts VALUES(1,200,'2026-01-01',NULL);
    """)
    return repo


@pytest.mark.parametrize(
    ("price", "delta", "percent"),
    [(20.48, 0.48, 2.4), (19.52, -0.48, -2.4), (20, 0, 0)],
)
def test_otec_effect_is_value_change_over_otec_price(price, delta, percent):
    repo = effect_repo()
    repo.quote("2026-10-05T14:45:00Z", price)
    result = asyncio.run(
        feature.bemobi_after_oslo(repo, now=dt("2026-10-05T15:00:00Z"))
    )
    effect = result["otec_effect"]
    assert effect["ready"]
    assert effect["change_per_share_nok"] == pytest.approx(delta)
    assert effect["change_pct"] == pytest.approx(percent)


def test_otec_effect_excludes_later_fx_prices_and_capital_changes():
    repo = effect_repo()
    repo.db.executescript("""
        INSERT INTO fx_rates VALUES(2,'BRL','NOK','9','2026-10-05T15:00:00Z',4);
        INSERT INTO market_prices VALUES(11,2,3,'100','2026-10-06T10:00:00Z','2026-10-06','LAST','{}');
        INSERT INTO bemobi_holdings VALUES(2,999,'2026-10-06',NULL);
        INSERT INTO otello_share_counts VALUES(2,999,'2026-10-06',NULL);
    """)
    result = asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))
    assert result["change_pct"] == pytest.approx(1.5)
    assert result["fixed_brl_nok"] == 2
    assert result["holding_shares"] == 100
    assert result["otec_outstanding_shares"] == 200


@pytest.mark.parametrize(
    "table,missing",
    [
        ("fx_rates", "fixed_fx"),
        ("bemobi_holdings", "bemobi_holding"),
        ("otello_share_counts", "otec_shares"),
        ("market_prices", "otec_close"),
    ],
)
def test_missing_otec_inputs_never_invent_effect(table, missing):
    repo = effect_repo()
    repo.db.execute(f"DELETE FROM {table}")
    result = asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))
    assert not result["ready"]
    assert missing in result["missing"]
    assert "change_pct" not in result


def test_effect_rejects_old_fx_invalid_denominator_and_post_auction_last():
    repo = effect_repo()
    repo.db.executescript("""
        UPDATE fx_rates SET observed_at='2026-09-01T12:00:00Z';
        UPDATE otello_share_counts SET outstanding_shares=0;
        UPDATE market_prices SET price_type='LAST',observed_at='2026-10-05T14:30:01Z' WHERE instrument_id=2;
    """)
    result = asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))
    assert set(result["missing"]) == {"fixed_fx", "otec_shares", "otec_close"}


def test_effect_uses_nearby_pre_close_last_only_when_close_missing():
    repo = effect_repo()
    repo.db.execute(
        "UPDATE market_prices SET price_type='LAST',observed_at='2026-10-05T14:15:00Z' WHERE instrument_id=2"
    )
    result = asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))
    assert result["ready"]
    assert result["otec_price_type"] == "LAST"
    assert result["change_pct"] == pytest.approx(1.5)


def test_reference_recovery_uses_only_near_close_delayed_b3_quotes():
    repo = Repository()
    repo.quote("2026-10-05T14:25:00Z", 20)
    repo.quote("2026-10-05T14:45:00Z", 21)
    result = asyncio.run(
        feature.recover_reference(repo, now=dt("2026-10-05T15:00:00Z"))
    )
    assert result["status"] == "ok"
    assert result["reference"]["recovered"]
    repo.quote("2026-10-05T14:24:59Z", 99)
    again = asyncio.run(feature.recover_reference(repo, now=dt("2026-10-05T15:00:00Z")))
    assert again["reason"] == "reference_already_captured"
    assert (
        asyncio.run(feature.bemobi_after_oslo(repo, now=dt("2026-10-05T15:00:00Z")))[
            "reference"
        ]["price"]
        == 20
    )


def test_reference_read_recovery_rejects_yahoo_and_wrong_delay():
    repo = Repository()
    repo.quote("2026-10-05T14:25:00Z", 20, source=2)
    assert (
        asyncio.run(
            feature.stored_reference(
                repo, dt("2026-10-05T14:25:00Z"), dt("2026-10-05T15:00:00Z")
            )
        )
        is None
    )
    repo.quote("2026-10-05T14:25:00Z", 20)
    repo.db.execute("UPDATE market_prices SET metadata_json='{}'")
    assert (
        asyncio.run(feature.recover_reference(repo, now=dt("2026-10-05T15:00:00Z")))[
            "status"
        ]
        == "missing"
    )


def test_effect_accepts_illiquid_same_day_trade_but_not_previous_day():
    repo = effect_repo()
    repo.db.execute(
        "UPDATE market_prices SET price_type='LAST',observed_at='2026-10-05T08:00:00Z' WHERE instrument_id=2"
    )
    assert asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))[
        "ready"
    ]
    repo.db.execute(
        "UPDATE market_prices SET trading_date='2026-10-02' WHERE instrument_id=2"
    )
    assert not asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))[
        "ready"
    ]


def test_effect_reads_daily_activity_but_prefers_official_close():
    repo = effect_repo()
    repo.db.execute(
        "INSERT INTO market_activity VALUES(1,2,3,'2026-10-05','10',?)",
        (json.dumps({"latest_trade_at": "2026-10-05T14:25:00Z"}),),
    )
    assert (
        asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))[
            "otec_price_nok"
        ]
        == 20
    )
    repo.db.execute("DELETE FROM market_prices WHERE instrument_id=2")
    result = asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))
    assert result["ready"] and result["otec_price_nok"] == 10
    assert result["otec_price_type"] == "LAST"
    repo.db.execute(
        "UPDATE market_activity SET metadata_json=?",
        (json.dumps({"latest_trade_at": "2026-10-05T14:30:01Z"}),),
    )
    assert not asyncio.run(feature.otec_effect(repo, dt("2026-10-05T14:25:00Z"), 0.3))[
        "ready"
    ]


def test_reference_job_does_not_require_nav_writer_lock(monkeypatch):
    import repository as repository_module

    class JobRepository(Repository):
        async def start_job(self, **kwargs):
            return 1

        async def finish_job(self, *args, **kwargs):
            self.finished = kwargs

    repo = JobRepository()
    monkeypatch.setattr(repository_module, "D1WriteRepository", lambda database: repo)

    async def capture(repository):
        return {"status": "ok"}

    monkeypatch.setattr(feature, "capture_reference", capture)
    result = asyncio.run(
        feature.run_reference_capture(object(), now=dt("2026-10-05T14:40:00Z"))
    )
    assert result["status"] == "ok"
    assert repo.finished["status"] == "SUCCESS"


def yahoo_payload(bars, **metadata):
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "BMOB3.SA",
                            "currency": "BRL",
                            "exchangeTimezoneName": "America/Sao_Paulo",
                            **metadata,
                        },
                        "timestamp": [int(dt(at).timestamp()) for at, _ in bars],
                        "indicators": {
                            "quote": [{"close": [price for _, price in bars]}]
                        },
                    }
                ],
                "error": None,
            }
        }
    ).encode()


def test_historical_reference_excludes_bar_starting_at_close_and_later_prices():
    payload = yahoo_payload(
        [
            ("2026-10-07T14:23:00Z", 31.07),
            ("2026-10-07T14:24:00Z", 31.09),
            ("2026-10-07T14:25:00Z", 31.05),
            ("2026-10-07T15:00:00Z", 32),
        ]
    )
    quote = feature.yahoo_reference_quote(
        payload, dt("2026-10-07T14:25:00Z"), dt("2026-10-07T15:00:00Z")
    )
    assert quote.price == feed.Decimal("31.09")
    assert quote.observed_at == "2026-10-07T14:25:00Z"
    assert quote.volume_shares is None


@pytest.mark.parametrize(
    "bars",
    [
        [("2026-10-07T14:20:00Z", 31)],
        [("2026-10-06T14:24:00Z", 31)],
        [("2026-10-07T14:25:00Z", 31)],
        [("2026-10-07T14:24:00Z", None)],
        [("2026-10-07T14:24:00Z", float("nan"))],
    ],
)
def test_historical_reference_rejects_missing_old_and_post_close_bars(bars):
    assert (
        feature.yahoo_reference_quote(
            yahoo_payload(bars), dt("2026-10-07T14:25:00Z"), dt("2026-10-07T15:00:00Z")
        )
        is None
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"symbol": "OTEC.OL"},
        {"currency": "NOK"},
        {"exchangeTimezoneName": "Europe/Oslo"},
    ],
)
def test_historical_reference_validates_instrument_currency_and_timezone(metadata):
    with pytest.raises(ValueError):
        feature.yahoo_reference_quote(
            yahoo_payload([("2026-10-07T14:24:00Z", 31)], **metadata),
            dt("2026-10-07T14:25:00Z"),
            dt("2026-10-07T15:00:00Z"),
        )


def test_recovery_backfills_once_after_b3_window_and_makes_card_ready(monkeypatch):
    repo = Repository()
    repo.quote("2026-10-07T14:45:00Z", 32)
    calls = []
    payload = yahoo_payload(
        [("2026-10-07T14:24:00Z", 31.09), ("2026-10-07T14:45:00Z", 32)]
    )

    async def download(**kwargs):
        calls.append("download")
        return "https://query1.finance.yahoo.com/chart", payload, None, "query1"

    async def persist(repository, quote, *args, **kwargs):
        calls.append("persist")
        repository.quote(quote.observed_at, quote.price, source=2)
        return 7

    monkeypatch.setattr(feed, "download_bmob3_yahoo_quote", download)
    monkeypatch.setattr(feed, "_persist_yahoo_quote", persist)
    early = asyncio.run(feature.recover_reference(repo, now=dt("2026-10-07T14:42:00Z")))
    assert early["status"] == "missing" and not calls
    result = asyncio.run(
        feature.recover_reference(repo, now=dt("2026-10-07T15:00:00Z"))
    )
    assert result["reference"]["source"] == "YAHOO_FINANCE"
    assert result["reference"]["bar_start_at"] == "2026-10-07T14:24:00Z"
    card = asyncio.run(feature.bemobi_after_oslo(repo, now=dt("2026-10-07T15:00:00Z")))
    assert card["ready"] and card["change_pct"] == pytest.approx((32 / 31.09 - 1) * 100)
    again = asyncio.run(feature.recover_reference(repo, now=dt("2026-10-07T15:30:00Z")))
    assert again["reason"] == "reference_already_captured"
    assert calls == ["download", "persist"]


def test_recovery_keeps_b3_priority_and_reports_network_failure(monkeypatch):
    calls = []

    async def unavailable(**kwargs):
        calls.append(1)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(feed, "download_bmob3_yahoo_quote", unavailable)
    repo = Repository()
    repo.quote("2026-10-07T14:25:00Z", 31)
    result = asyncio.run(
        feature.recover_reference(repo, now=dt("2026-10-07T15:00:00Z"))
    )
    assert result["reference"]["source"] == "B3" and not calls
    result = asyncio.run(
        feature.recover_reference(Repository(), now=dt("2026-10-07T15:00:00Z"))
    )
    assert result["reason"] == "historical_reference_unavailable"
    assert "change_pct" not in result


@pytest.mark.parametrize(
    "close,bar",
    [
        ("2026-11-02T15:25:00Z", "2026-11-02T15:24:00Z"),
        ("2026-04-01T11:05:00Z", "2026-04-01T11:04:00Z"),
    ],
)
def test_historical_reference_handles_winter_and_half_day(close, bar):
    quote = feature.yahoo_reference_quote(
        yahoo_payload([(bar, 31)]), dt(close), dt(close)
    )
    assert quote.observed_at == close
    assert (
        feature.yahoo_reference_quote(yahoo_payload([(bar, 31)]), dt(close), dt(bar))
        is None
    )


def test_historical_recovery_does_not_hide_persistence_failure(monkeypatch):
    async def download(**kwargs):
        return "yahoo", yahoo_payload([("2026-10-07T14:24:00Z", 31)]), None, "query1"

    async def persist(*args, **kwargs):
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(feed, "download_bmob3_yahoo_quote", download)
    monkeypatch.setattr(feed, "_persist_yahoo_quote", persist)
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(
            feature.recover_reference(Repository(), now=dt("2026-10-07T15:00:00Z"))
        )


@pytest.mark.parametrize("source_table", ["market_prices", "market_activity"])
@pytest.mark.parametrize("day", ["2026-10-07", "2026-12-07", "2026-04-01"])
def test_effect_includes_euronext_closing_auction_in_theoretical_price(
    source_table, day
):
    repo = effect_repo()
    close = feature.closing_auction(dt(day).date())
    before = feature.iso(close - timedelta(seconds=30))
    execution = feature.iso(close + timedelta(seconds=30))
    repo.db.execute(
        "UPDATE market_prices SET price_type='LAST',price='20.05',trading_date=?,observed_at=? WHERE instrument_id=2",
        (day, before),
    )
    repo.db.execute("UPDATE fx_rates SET observed_at=?", (before,))
    repo.db.execute("UPDATE bemobi_holdings SET effective_from=?", (day,))
    repo.db.execute("UPDATE otello_share_counts SET effective_from=?", (day,))
    if source_table == "market_prices":
        repo.db.execute(
            "INSERT INTO market_prices VALUES(11,2,3,'20',?,?,'LAST','{}')",
            (execution, day),
        )
    else:
        repo.db.execute(
            "INSERT INTO market_activity VALUES(1,2,3,?,'20',?)",
            (day, json.dumps({"latest_trade_at": execution})),
        )
    result = asyncio.run(feature.otec_effect(repo, close, -0.01))
    assert result["ready"]
    assert result["otec_price_nok"] == 20
    assert result["otec_observed_at"] == execution
    assert result["change_pct"] == pytest.approx(-0.05)
    assert result["otec_price_nok"] + result["change_per_share_nok"] == pytest.approx(
        19.99
    )


def test_effect_keeps_official_close_and_excludes_later_other_source_quotes():
    repo = effect_repo()
    repo.db.execute(
        "INSERT INTO market_prices VALUES(11,2,2,'99','2026-10-05T14:25:30Z','2026-10-05','LAST','{}')"
    )
    close = dt("2026-10-05T14:25:00Z")
    assert asyncio.run(feature.otec_effect(repo, close, -0.01))["otec_price_nok"] == 20
    repo.db.execute(
        "UPDATE market_prices SET price_type='LAST',observed_at='2026-10-05T14:24:00Z' WHERE id=10"
    )
    assert asyncio.run(feature.otec_effect(repo, close, -0.01))["otec_price_nok"] == 20
