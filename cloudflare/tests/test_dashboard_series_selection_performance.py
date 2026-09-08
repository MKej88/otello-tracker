from __future__ import annotations

import asyncio

import pytest

from src.dashboard_service import (
    CORE_CALCULATION_VERSION,
    FULL_CALCULATION_VERSION,
    _preferred_nav_series,
)


class RecordingRepository:
    def __init__(self, row: dict[str, str | None] | None) -> None:
        self.row = row
        self.queries = 0

    async def first(self, sql: str, parameters: tuple[str, ...] = ()):
        self.queries += 1
        assert "AS core_date" in sql
        assert "AS full_date" in sql
        assert parameters == (
            CORE_CALCULATION_VERSION,
            FULL_CALCULATION_VERSION,
            CORE_CALCULATION_VERSION,
            FULL_CALCULATION_VERSION,
        )
        return self.row


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {"core_date": "2026-09-08", "full_date": "2026-09-08"},
            (FULL_CALCULATION_VERSION, "FULL"),
        ),
        (
            {"core_date": "2026-09-08", "full_date": "2026-09-07"},
            (CORE_CALCULATION_VERSION, "CORE"),
        ),
        (
            {"core_date": None, "full_date": "2026-09-08"},
            (FULL_CALCULATION_VERSION, "FULL"),
        ),
        (
            {"core_date": None, "full_date": None},
            (CORE_CALCULATION_VERSION, "CORE"),
        ),
        (None, (CORE_CALCULATION_VERSION, "CORE")),
    ],
)
def test_series_selection_uses_one_query_without_changing_fallbacks(
    row: dict[str, str | None] | None,
    expected: tuple[str, str],
) -> None:
    repository = RecordingRepository(row)

    result = asyncio.run(_preferred_nav_series(repository))

    assert result == expected
    assert repository.queries == 1


def test_series_selection_still_propagates_database_errors() -> None:
    class FailingRepository:
        async def first(self, sql: str, parameters: tuple[str, ...] = ()):
            raise RuntimeError("simulert databasefeil")

    with pytest.raises(RuntimeError, match="simulert databasefeil"):
        asyncio.run(_preferred_nav_series(FailingRepository()))
