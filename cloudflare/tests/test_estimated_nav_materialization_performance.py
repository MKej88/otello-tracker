from __future__ import annotations

import asyncio
from unittest.mock import patch

from src.estimated_nav_history_materialization import (
    materialize_estimated_nav_history_batch,
)


class CountingRepository:
    def __init__(self, dates: list[str]) -> None:
        self.dates = dates
        self.read_calls = 0
        self.write_calls = 0
        self.batch_calls = 0
        self.batched_statements: list[list[tuple[str, tuple[object, ...]]]] = []

    async def all(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        self.read_calls += 1
        if "ECONOMIC_NAV_COST_ANCHOR" in sql:
            return [{"scenario": "BASE", "effective_from": "2023-06-30",
                     "amount_usd": "1673000", "period_days": 181}]
        if "SELECT DISTINCT" in sql:
            return [{"date": day} for day in self.dates]
        raise AssertionError(f"Uventet SQL: {sql}")

    async def first(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> dict[str, object] | None:
        self.read_calls += 1
        return None

    async def run(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self.write_calls += 1

    async def run_batch(self, statements: list[tuple[str, tuple[object, ...]]]) -> None:
        self.batch_calls += 1
        self.batched_statements.append(statements)


async def _ready_point(repository: object, day: str) -> dict[str, object]:
    return {
        "ready": True,
        "nav_total_mnok": 1,
        "nav_per_share": 2,
        "otec_price": 3,
        "discount_pct": 4,
        "shares_outstanding": 5,
        "accounting_nav_per_share": 6,
        "composition": {"date": day},
        "reconciliation_residual_mnok": 0,
    }


def test_successful_days_batch_point_and_retry_cleanup_per_day() -> None:
    dates = [f"2026-01-{day:02d}" for day in range(1, 11)]
    repository = CountingRepository(dates)

    with patch(
        "src.estimated_nav_history_materialization._estimated_point",
        _ready_point,
    ):
        result = asyncio.run(
            materialize_estimated_nav_history_batch(repository, batch_size=10)
        )

    assert result["written"] == 10
    assert repository.batch_calls == 10
    assert repository.write_calls == 1  # The scan cursor is still one separate write.
    assert all(len(statements) == 3 for statements in repository.batched_statements)
    for statements, day in zip(repository.batched_statements, dates, strict=True):
        point_write, retry_cleanup, period_invalidation = statements
        assert point_write[1][0] == day
        assert retry_cleanup[1][0] == day
        assert len(period_invalidation[1]) == 6


def test_history_before_anchor_is_parked_and_reactivated_without_deletion() -> None:
    import sqlite3
    from src.estimated_nav_history_materialization import _retry_due_failures, _queue_coverage_gap

    class Repository:
        def __init__(self):
            self.db = sqlite3.connect(":memory:")
            self.db.row_factory = sqlite3.Row
            self.db.executescript("""
                CREATE TABLE estimated_nav_history_retry_queue(
                  date TEXT, calculation_version TEXT, reason TEXT, attempts INTEGER,
                  first_failed_at TEXT DEFAULT '2026-01-01',
                  last_failed_at TEXT DEFAULT '2026-01-01', next_retry_at TEXT,
                  PRIMARY KEY(date,calculation_version));
                CREATE TABLE estimated_nav_history_points(date,calculation_version,quality);
            """)
        async def run(self, sql, parameters=()):
            self.db.execute(sql, parameters)
        async def all(self, sql, parameters=()):
            return [dict(row) for row in self.db.execute(sql, parameters)]
        async def first(self, sql, parameters=()):
            rows = await self.all(sql, parameters)
            return rows[0] if rows else None

    async def exercise():
        repository = Repository()
        await _queue_coverage_gap(repository, "2023-06-29")
        await _queue_coverage_gap(repository, "2023-06-29")
        repository.db.execute(
            "UPDATE estimated_nav_history_retry_queue SET reason='missing_estimated_nav_anchor', attempts=6"
        )
        calls = []
        async def unavailable(repo, day):
            calls.append(day)
            return {"ready": False, "reason": "missing_option_inputs"}
        with patch("src.estimated_nav_history_materialization._estimated_point", unavailable):
            result = await _retry_due_failures(repository, first_base="2023-06-30")
            assert result["pending"] == 0
            assert result["parked_before_cost_anchor"] == 1
            assert result["attempted"] == 0
            assert calls == []
            assert repository.db.execute("SELECT attempts FROM estimated_nav_history_retry_queue").fetchone()[0] == 6
            reopened = await _retry_due_failures(repository, first_base="2023-06-29")
            assert calls == ["2023-06-29"]
            assert reopened["parked_before_cost_anchor"] == 0
            assert reopened["pending"] == 1
            assert reopened["attempted"] == 1
        repository.db.close()

    asyncio.run(exercise())
