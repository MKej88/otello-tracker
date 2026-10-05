from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime
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
            INSERT INTO instruments VALUES(1,'BMOB3');
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
