from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from history_rebuild_state import (  # noqa: E402
    history_window_complete,
    mark_history_window_complete,
    next_history_rebuild_chunk,
)


class FakeRepository:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.run_parameters: tuple[str, str] | None = None

    async def first(
        self, query: str, parameters: tuple[str, ...]
    ) -> dict[str, str] | None:
        del query, parameters
        return {"value": self.value} if self.value is not None else None

    async def run(self, query: str, parameters: tuple[str, str]) -> dict[str, Any]:
        del query
        self.run_parameters = parameters
        return {}


class HistoryWindowCompleteTest(unittest.IsolatedAsyncioTestCase):
    async def test_requires_marker_to_cover_the_requested_window(self) -> None:
        repository = FakeRepository('{"from":"2025-01-01","to":"2025-06-30"}')

        self.assertTrue(
            await history_window_complete(
                repository,
                start_date="2025-02-01",
                end_date="2025-06-01",
            )
        )
        self.assertFalse(
            await history_window_complete(
                repository,
                start_date="2025-02-01",
                end_date="2025-07-01",
            )
        )

    async def test_rejects_a_window_across_calendar_years(self) -> None:
        with self.assertRaisesRegex(ValueError, "ett kalenderår"):
            await history_window_complete(
                FakeRepository(),
                start_date="2025-12-31",
                end_date="2026-01-01",
            )


class NextHistoryRebuildChunkTest(unittest.IsolatedAsyncioTestCase):
    async def test_resumes_after_the_existing_contiguous_marker(self) -> None:
        repository = FakeRepository('{"from":"2025-01-01","to":"2025-01-10"}')

        chunk = await next_history_rebuild_chunk(
            repository,
            start_date="2025-01-01",
            end_date="2025-02-28",
            max_days=7,
        )

        self.assertEqual(chunk, ("2025-01-11", "2025-01-17"))

    async def test_rejects_a_marker_that_leaves_a_gap(self) -> None:
        repository = FakeRepository('{"from":"2025-01-02","to":"2025-01-10"}')

        with self.assertRaisesRegex(ValueError, "ikke sammenhengende"):
            await next_history_rebuild_chunk(
                repository,
                start_date="2025-01-01",
                end_date="2025-02-28",
            )


class MarkHistoryWindowCompleteTest(unittest.IsolatedAsyncioTestCase):
    async def test_merges_overlapping_windows_before_saving(self) -> None:
        repository = FakeRepository('{"from":"2025-01-10","to":"2025-01-20"}')

        await mark_history_window_complete(
            repository,
            start_date="2025-01-01",
            end_date="2025-01-12",
        )

        assert repository.run_parameters is not None
        key, value = repository.run_parameters
        self.assertEqual(key, "norges_bank_nav_history_v1:2025")
        self.assertEqual(
            json.loads(value),
            {"from": "2025-01-01", "to": "2025-01-20"},
        )

    async def test_rejects_non_contiguous_windows(self) -> None:
        repository = FakeRepository('{"from":"2025-01-10","to":"2025-01-20"}')

        with self.assertRaisesRegex(ValueError, "ikke-sammenhengende"):
            await mark_history_window_complete(
                repository,
                start_date="2025-02-01",
                end_date="2025-02-10",
            )


if __name__ == "__main__":
    unittest.main()
