from __future__ import annotations

import asyncio
import sqlite3

import pytest

from src.d1_preflight import CASH_FX_LOOKBACK_DAYS, _cash_anchor_fx_gaps


class RecordingRepository:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[str, ...]]] = []

    async def all(
        self, sql: str, parameters: tuple[str, ...] = ()
    ) -> list[dict[str, str]]:
        self.queries.append((sql, parameters))
        return self.rows


def test_cash_anchor_fx_gaps_are_loaded_with_one_query() -> None:
    repository = RecordingRepository(
        [
            {"as_of_date": "2026-01-10", "reported_currency": "USD"},
            {"as_of_date": "2026-02-01", "reported_currency": "BRL"},
        ]
    )

    result = asyncio.run(_cash_anchor_fx_gaps(repository))

    assert result == [
        {
            "anchor_date": "2026-01-10",
            "currency": "USD",
            "required_window": ["2026-01-03", "2026-01-10"],
        },
        {
            "anchor_date": "2026-02-01",
            "currency": "BRL",
            "required_window": ["2026-01-25", "2026-02-01"],
        },
    ]
    assert len(repository.queries) == 1
    sql, parameters = repository.queries[0]
    assert "NOT EXISTS" in sql
    assert "fx.base_currency=ca.reported_currency" in sql
    assert parameters == (f"-{CASH_FX_LOOKBACK_DAYS} days",)


def test_cash_anchor_fx_gap_query_still_propagates_database_errors() -> None:
    class FailingRepository:
        async def all(self, sql: str, parameters: tuple[str, ...] = ()):
            raise RuntimeError("simulert databasefeil")

    with pytest.raises(RuntimeError, match="simulert databasefeil"):
        asyncio.run(_cash_anchor_fx_gaps(FailingRepository()))


def test_cash_anchor_fx_gaps_keep_existing_window_semantics() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE cash_anchors(
            as_of_date TEXT, reported_currency TEXT, anchor_type TEXT
        );
        CREATE TABLE fx_rates(
            observed_at TEXT, base_currency TEXT, quote_currency TEXT
        );
        INSERT INTO cash_anchors VALUES
            ('2026-01-10', 'USD', 'REPORTED'),
            ('2026-02-01', 'BRL', 'REPORTED'),
            ('2026-03-01', 'NOK', 'REPORTED');
        INSERT INTO fx_rates VALUES ('2026-01-03T12:00:00Z', 'USD', 'NOK');
        """)

    class SQLiteRepository:
        async def all(self, sql: str, parameters: tuple[str, ...] = ()):
            return [dict(row) for row in connection.execute(sql, parameters)]

    result = asyncio.run(_cash_anchor_fx_gaps(SQLiteRepository()))

    assert result == [
        {
            "anchor_date": "2026-02-01",
            "currency": "BRL",
            "required_window": ["2026-01-25", "2026-02-01"],
        }
    ]
