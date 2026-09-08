from __future__ import annotations

import asyncio
import json

from src.materialized_discount_history import (
    PERIOD_CACHE_VERSION,
    PERIOD_KEYS,
    _cache_key,
    materialized_nav_period_bundle,
)


class RecordingRepository:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[str, ...]]] = []

    async def first(
        self, sql: str, parameters: tuple[str, ...] = ()
    ) -> dict[str, str]:
        self.queries.append((sql, parameters))
        return {"max_date": "2026-09-08"}

    async def all(
        self, sql: str, parameters: tuple[str, ...] = ()
    ) -> list[dict[str, str]]:
        self.queries.append((sql, parameters))
        return self.rows


def _row(period_key: str, *, ready: bool = True) -> dict[str, str]:
    return {
        "key": _cache_key(period_key),
        "value": json.dumps(
            {
                "source_date": "2026-09-08",
                "calculation_version": PERIOD_CACHE_VERSION,
                "payload": {
                    "estimated": {"ready": ready, "period_key": period_key}
                },
            }
        ),
        "updated_at": f"2026-09-08T00:00:0{PERIOD_KEYS.index(period_key)}Z",
    }


def test_bundle_loads_all_periods_in_one_query() -> None:
    repository = RecordingRepository([_row(key) for key in reversed(PERIOD_KEYS)])

    result = asyncio.run(materialized_nav_period_bundle(repository))

    assert len(repository.queries) == 2
    assert repository.queries[1][1] == tuple(_cache_key(key) for key in PERIOD_KEYS)
    assert list(result["periods"]) == list(PERIOD_KEYS)
    assert result["ready"] is True
    assert result["calculated_at"] == "2026-09-08T00:00:05Z"


def test_bundle_preserves_missing_and_invalid_period_semantics() -> None:
    rows = [_row(key) for key in PERIOD_KEYS if key != "3m"]
    rows[1] = _row("6m", ready=False)
    repository = RecordingRepository(rows)

    result = asyncio.run(materialized_nav_period_bundle(repository))

    assert result["ready"] is False
    assert result["missing_periods"] == ["3m", "6m"]
    assert list(result["periods"]) == ["1m", "ytd", "1y", "3y"]
