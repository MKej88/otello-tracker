from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from history_rebuild_state import (  # noqa: E402
    STATE_PREFIX,
    history_rebuild_needed,
    history_window_complete,
    mark_history_window_complete,
)


class _StateRepository:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    async def first(self, sql: str, parameters=()):
        assert "FROM runtime_state" in sql
        value = self.values.get(parameters[0])
        return {"value": value} if value is not None else None

    async def all(self, sql: str, parameters=()):
        assert "FROM runtime_state" in sql
        prefix = str(parameters[0]).rstrip("%")
        return [
            {"key": key, "value": value}
            for key, value in sorted(self.values.items())
            if key.startswith(prefix)
        ]

    async def run(self, sql: str, parameters=()):
        assert "INSERT INTO runtime_state" in sql
        key, value = parameters
        self.values[str(key)] = str(value)


def _marker(start: str, end: str) -> str:
    return json.dumps({"from": start, "to": end}, sort_keys=True, separators=(",", ":"))


def test_completed_year_window_is_checkpointed_and_skippable() -> None:
    repository = _StateRepository()
    asyncio.run(
        mark_history_window_complete(
            repository,
            start_date="2021-01-01",
            end_date="2021-12-31",
        )
    )

    assert asyncio.run(
        history_window_complete(
            repository,
            start_date="2021-01-01",
            end_date="2021-12-31",
        )
    ) is True


def test_missing_year_keeps_ten_year_rebuild_pending() -> None:
    values = {
        f"{STATE_PREFIX}2016": _marker("2016-08-21", "2016-12-31"),
        **{
            f"{STATE_PREFIX}{year}": _marker(f"{year}-01-01", f"{year}-12-31")
            for year in range(2017, 2026)
            if year != 2021
        },
        f"{STATE_PREFIX}2026": _marker("2026-01-01", "2026-08-21"),
    }
    repository = _StateRepository(values)

    assert asyncio.run(
        history_rebuild_needed(
            repository,
            required_start="2016-08-21",
            target_date="2026-08-22",
        )
    ) is True


def test_completed_bootstrap_does_not_repeat_when_target_advances_one_day() -> None:
    values = {
        f"{STATE_PREFIX}2016": _marker("2016-08-21", "2016-12-31"),
        **{
            f"{STATE_PREFIX}{year}": _marker(f"{year}-01-01", f"{year}-12-31")
            for year in range(2017, 2026)
        },
        f"{STATE_PREFIX}2026": _marker("2026-01-01", "2026-08-21"),
    }
    repository = _StateRepository(values)

    assert asyncio.run(
        history_rebuild_needed(
            repository,
            required_start="2016-08-22",
            target_date="2026-08-22",
        )
    ) is False
