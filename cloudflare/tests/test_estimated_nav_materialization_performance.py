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
    assert all(len(statements) == 2 for statements in repository.batched_statements)
    for statements, day in zip(repository.batched_statements, dates, strict=True):
        point_write, retry_cleanup = statements
        assert point_write[1][0] == day
        assert retry_cleanup[1][0] == day
