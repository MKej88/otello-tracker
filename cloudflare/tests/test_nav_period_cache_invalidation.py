from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from src import estimated_nav_history_materialization as history
from src import materialized_discount_history as periods


class SQLiteRepository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        migrations = Path(__file__).resolve().parents[2] / "backend/app/db/migrations"
        for name in (
            "0016_runtime_state.sql",
            "0034_materialized_estimated_nav_history.sql",
            "0035_estimated_nav_history_retry_queue.sql",
        ):
            self.connection.executescript((migrations / name).read_text())

    async def all(self, sql, parameters=()):
        return [dict(row) for row in self.connection.execute(sql, parameters)]

    async def first(self, sql, parameters=()):
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None

    async def run(self, sql, parameters=()):
        with self.connection:
            self.connection.execute(sql, parameters)

    async def run_batch(self, statements):
        with self.connection:
            for sql, parameters in statements:
                self.connection.execute(sql, parameters)


def point(nav_per_share):
    return {
        "nav_total_mnok": nav_per_share * 10,
        "nav_per_share": nav_per_share,
        "otec_price": 5,
        "discount_pct": (1 - 5 / nav_per_share) * 100,
        "shares_outstanding": 10_000_000,
        "accounting_nav_per_share": 9,
        "composition": [],
        "reconciliation_residual_mnok": 0,
    }


@pytest.mark.parametrize("corrected_day", ["2026-09-03", "2026-09-04"])
def test_corrected_history_is_not_served_from_old_period_cache(
    monkeypatch, corrected_day
):
    async def scenario():
        repository = SQLiteRepository()
        try:
            for day in ("2026-09-03", "2026-09-04"):
                await history._write_point_and_remove_retry(repository, day, point(10))

            async def calculate(repo, **kwargs):
                rows = await repo.all(
                    "SELECT * FROM estimated_nav_history_points ORDER BY date"
                )
                return {
                    "estimated": {
                        "ready": True,
                        "to": rows[-1]["date"],
                        "points": [
                            {
                                "date": row["date"],
                                "nav_per_share": row["nav_per_share_nok"],
                            }
                            for row in rows
                        ],
                    }
                }

            monkeypatch.setattr(periods, "discount_history", calculate)
            assert (await periods.materialize_discount_periods(repository))[
                "written"
            ] == 6
            assert (await periods.materialized_nav_period_bundle(repository))[
                "ready"
            ] is True
            await repository.run(
                "INSERT INTO runtime_state(key, value) VALUES ('unrelated', 'keep')"
            )

            # A corrected FULL NAV or a successful retry rewrites a historical day
            # without advancing MAX(date). The next period build can fail independently.
            await history._write_point_and_remove_retry(
                repository, corrected_day, point(11)
            )
            assert (await periods.materialized_nav_period_bundle(repository))[
                "ready"
            ] is False

            async def failed_calculation(*args, **kwargs):
                raise RuntimeError("period calculation failed")

            monkeypatch.setattr(periods, "discount_history", failed_calculation)
            assert (await periods.materialize_discount_periods(repository))[
                "status"
            ] == "partial"

            bundle = await periods.materialized_nav_period_bundle(repository)
            assert bundle["ready"] is False
            assert bundle["periods"] == {}
            assert bundle["missing_periods"] == list(periods.PERIOD_KEYS)

            # The endpoint must propagate an unavailable live calculation instead
            # of returning HTTP-success data from the obsolete cache.
            with pytest.raises(RuntimeError, match="period calculation failed"):
                await periods.materialized_discount_history(
                    repository, days=31, max_points=72
                )

            monkeypatch.setattr(periods, "discount_history", calculate)
            response = await periods.materialized_discount_history(
                repository, days=31, max_points=72
            )
            values = {
                row["date"]: row["nav_per_share"]
                for row in response["estimated"]["points"]
            }
            assert values[corrected_day] == 11
            assert (
                await repository.first(
                    "SELECT value FROM runtime_state WHERE key='unrelated'"
                )
            )["value"] == "keep"
            assert (await periods.materialize_discount_periods(repository))[
                "written"
            ] == 6
            assert (await periods.materialized_nav_period_bundle(repository))[
                "ready"
            ] is True
        finally:
            repository.connection.close()

    asyncio.run(scenario())


def test_cache_invalidation_failure_rolls_back_history_write():
    async def scenario():
        repository = SQLiteRepository()
        try:
            await history._write_point_and_remove_retry(
                repository, "2026-09-04", point(10)
            )
            await repository.run(
                "INSERT INTO runtime_state(key, value) VALUES (?, '{}')",
                (periods._cache_key("1m"),),
            )
            repository.connection.executescript(
                """CREATE TRIGGER fail_cache_delete BEFORE DELETE ON runtime_state
                   BEGIN SELECT RAISE(ABORT, 'cache deletion failed'); END;"""
            )

            with pytest.raises(sqlite3.IntegrityError, match="cache deletion failed"):
                await history._write_point_and_remove_retry(
                    repository, "2026-09-04", point(11)
                )

            row = await repository.first(
                "SELECT nav_per_share_nok FROM estimated_nav_history_points"
            )
            assert row["nav_per_share_nok"] == 10
            assert await repository.first("SELECT value FROM runtime_state") is not None
        finally:
            repository.connection.close()

    asyncio.run(scenario())
