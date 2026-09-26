from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import date, timedelta

from src.fx_backtest import _rates_for_days, fx_backtest_summary


class _Repository:
    def __init__(self) -> None:
        self.reads = 0
        self.fx_reads = 0

    async def all(self, sql: str, parameters: tuple = ()) -> list[dict]:
        self.reads += 1
        if "document_type='ECONOMIC_NAV_CASH_FX_ANCHOR'" in sql:
            return [
                {
                    "id": 2,
                    "metadata_json": json.dumps(
                        {
                            "as_of_date": "2026-04-11",
                            "total_cash_usd": "100",
                            "exposures": [],
                        }
                    ),
                },
                {
                    "id": 1,
                    "metadata_json": json.dumps(
                        {
                            "as_of_date": "2026-01-01",
                            "total_cash_usd": "0",
                            "exposures": [],
                        }
                    ),
                },
            ]
        if "document_type='ECONOMIC_NAV_FX_BACKTEST_OUTCOME'" in sql:
            return [
                {
                    "id": 3,
                    "metadata_json": json.dumps(
                        {
                            "period_start": "2026-01-01",
                            "period_end": "2026-04-11",
                            "cash_fx_effect_usd": "0",
                            "pnl_fx_result_usd": "0",
                        }
                    ),
                }
            ]
        if "FROM cash_movements" in sql:
            start = date(2026, 1, 2)
            return [
                {
                    "movement_date": (start + timedelta(days=offset)).isoformat(),
                    "amount_original": "1",
                    "currency": "USD",
                }
                for offset in range(100)
            ]
        if "WITH requested(day)" in sql:
            self.fx_reads += 1
            assert len(parameters) <= 90
            assert "ROW_NUMBER() OVER" in sql
            assert "WHEN 'NORGES_BANK' THEN 0" in sql
            assert "date(requested.day, '-7 days')" in sql
            return [
                {
                    "day": day,
                    "base_currency": currency,
                    "rate_date": day,
                    "rate": "10" if currency == "USD" else "2",
                }
                for day in parameters
                for currency in ("BRL", "USD")
            ]
        raise AssertionError(f"Uventet spørring: {sql}")


def test_backtest_batches_fx_rates_for_many_movement_days() -> None:
    repository = _Repository()

    result = asyncio.run(fx_backtest_summary(repository))

    assert result["ready"] is True
    assert result["periods"][0]["applied_known_movements"] == 100
    assert result["periods"][0]["skipped_movements"] == 0
    assert result["periods"][0]["model_cash_fx_usd_m"] == 0.0
    assert repository.fx_reads == 2
    assert repository.reads == 5


class _SqliteRepository:
    def __init__(self) -> None:
        self.database = sqlite3.connect(":memory:")
        self.database.row_factory = sqlite3.Row
        self.database.executescript(
            """
            CREATE TABLE sources(id INTEGER PRIMARY KEY, code TEXT);
            CREATE TABLE fx_rates(
                id INTEGER PRIMARY KEY,
                source_id INTEGER,
                base_currency TEXT,
                quote_currency TEXT,
                observed_at TEXT,
                rate TEXT
            );
            INSERT INTO sources VALUES (1, 'NORGES_BANK'), (2, 'ECB');
            INSERT INTO fx_rates VALUES
                (1, 2, 'USD', 'NOK', '2026-01-09T16:00:00Z', '11'),
                (2, 1, 'USD', 'NOK', '2026-01-09T12:00:00Z', '10'),
                (3, 1, 'BRL', 'NOK', '2026-01-09T12:00:00Z', '2');
            """
        )

    async def all(self, sql: str, parameters: tuple = ()) -> list[dict]:
        return [dict(row) for row in self.database.execute(sql, parameters)]


def test_batched_rates_preserve_source_priority_and_seven_day_lookback() -> None:
    repository = _SqliteRepository()

    rates = asyncio.run(
        _rates_for_days(repository, ["2026-01-10", "2026-01-17"])
    )

    assert rates["2026-01-10"] == (10, 2, "2026-01-09", "2026-01-09")
    assert "2026-01-17" not in rates
