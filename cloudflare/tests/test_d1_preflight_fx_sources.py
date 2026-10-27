"""Regression checks for target-dated BRL/NOK nightly preflight."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import date

from src.d1_preflight import _fresh_enough, _fx_coverage


class SQLiteFXRepository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE sources(id INTEGER PRIMARY KEY, code TEXT NOT NULL);
            CREATE TABLE fx_rates(
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL,
                base_currency TEXT NOT NULL,
                quote_currency TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                rate TEXT NOT NULL
            );
            INSERT INTO sources VALUES (1, 'NORGES_BANK'),
                                       (2, 'EXCHANGERATE_DEV'),
                                       (3, 'UNTRUSTED');
            """
        )

    def add(self, day: str, *, source: int = 1, base: str = "BRL", rate: str = "1.7") -> None:
        self.connection.execute(
            """INSERT INTO fx_rates(source_id,base_currency,quote_currency,observed_at,rate)
               VALUES (?, ?, 'NOK', ?, ?)""",
            (source, base, day, rate),
        )

    async def first(self, sql: str, params: tuple = ()) -> dict | None:
        row = self.connection.execute(sql, params).fetchone()
        return dict(row) if row is not None else None


def test_next_day_exr_quote_does_not_block_previous_day_nightly() -> None:
    repo = SQLiteFXRepository()
    repo.add("2016-08-22T00:00:00Z")
    repo.add("2026-10-26T00:00:00Z")
    repo.add("2026-10-26T15:59:00Z", source=2)
    repo.add("2026-10-27T00:10:00Z", source=2)
    repo.add("2026-10-27T00:15:00Z", source=3)

    coverage = asyncio.run(_fx_coverage(repo, "BRL", as_of_date="2026-10-26"))

    assert coverage["from"] == "2016-08-22"
    assert coverage["to"] == "2026-10-26"
    assert coverage["count"] == 3
    assert coverage["allowed_sources"] == ["NORGES_BANK", "EXCHANGERATE_DEV"]
    assert _fresh_enough(coverage["to"], date(2026, 10, 26))


def test_valid_exr_on_target_day_can_supply_current_brl_coverage() -> None:
    repo = SQLiteFXRepository()
    repo.add("2026-10-15T00:00:00Z")
    repo.add("2026-10-26T17:00:00Z", source=2)

    coverage = asyncio.run(_fx_coverage(repo, "BRL", as_of_date="2026-10-26"))

    assert coverage["to"] == "2026-10-26"
    assert _fresh_enough(coverage["to"], date(2026, 10, 26))


def test_future_only_exr_quote_cannot_hide_stale_historical_rate() -> None:
    repo = SQLiteFXRepository()
    repo.add("2026-10-15T00:00:00Z")
    repo.add("2026-10-27T00:01:00Z", source=2)

    coverage = asyncio.run(_fx_coverage(repo, "BRL", as_of_date="2026-10-26"))

    assert coverage["to"] == "2026-10-15"
    assert not _fresh_enough(coverage["to"], date(2026, 10, 26))


def test_unapproved_provider_and_live_brl_source_cannot_supply_usd() -> None:
    repo = SQLiteFXRepository()
    repo.add("2026-10-26T12:00:00Z", source=3)
    repo.add("2026-10-26T13:00:00Z", source=2, base="USD")
    repo.add("2026-10-15T00:00:00Z", source=1, base="USD")

    brl = asyncio.run(_fx_coverage(repo, "BRL", as_of_date="2026-10-26"))
    usd = asyncio.run(_fx_coverage(repo, "USD", as_of_date="2026-10-26"))

    assert brl["count"] == 0
    assert brl["to"] is None
    assert not _fresh_enough(brl["to"], date(2026, 10, 26))
    assert usd["to"] == "2026-10-15"
    assert usd["allowed_sources"] == ["NORGES_BANK"]
