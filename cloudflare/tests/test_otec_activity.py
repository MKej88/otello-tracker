from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

import otec_activity  # noqa: E402


OSLO_TZ = ZoneInfo("Europe/Oslo")


class _ActivityRepository:
    def __init__(self, stored_dates: set[str] | None = None) -> None:
        self.stored_dates = stored_dates or set()

    async def first(
        self,
        _sql: str,
        parameters: tuple[object, ...] = (),
    ) -> dict[str, int] | None:
        if parameters and str(parameters[0]) in self.stored_dates:
            return {"ok": 1}
        return None


class OtecActivityRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_current_day_at_exact_end_of_day_boundary(self) -> None:
        repository = _ActivityRepository({"2026-09-24"})
        download = AsyncMock(return_value=("https://example.test/activity", b"zip"))
        ingest = AsyncMock(return_value={"status": "ok"})

        with (
            patch.object(otec_activity, "_download_activity", download),
            patch.object(otec_activity, "ingest_otec_daily_activity", ingest),
        ):
            result = await otec_activity.refresh_otec_daily_activity(
                repository,
                now=datetime(2026, 9, 25, 16, 45, tzinfo=OSLO_TZ),
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["written"], 1)
        download.assert_awaited_once_with(
            otec_activity.CURRENT_DAY_SELECTION,
            fetcher=None,
        )
        self.assertEqual(ingest.await_args.kwargs["target_date"], "2026-09-25")

    async def test_weekend_only_repairs_previous_trading_day(self) -> None:
        repository = _ActivityRepository()
        download = AsyncMock(return_value=("https://example.test/activity", b"zip"))
        ingest = AsyncMock(return_value={"status": "ok"})

        with (
            patch.object(otec_activity, "_download_activity", download),
            patch.object(otec_activity, "ingest_otec_daily_activity", ingest),
        ):
            result = await otec_activity.refresh_otec_daily_activity(
                repository,
                now=datetime(2026, 9, 27, 18, 0, tzinfo=OSLO_TZ),
            )

        self.assertEqual(result["written"], 1)
        download.assert_awaited_once_with(
            otec_activity.PREVIOUS_DAY_SELECTION,
            fetcher=None,
        )
        self.assertEqual(ingest.await_args.kwargs["target_date"], "2026-09-25")

    async def test_stored_days_are_not_downloaded_or_written_again(self) -> None:
        repository = _ActivityRepository({"2026-09-24", "2026-09-25"})
        fetcher = AsyncMock(side_effect=AssertionError("should not fetch stored days"))

        result = await otec_activity.refresh_otec_daily_activity(
            repository,
            now=datetime(2026, 9, 25, 17, 0, tzinfo=OSLO_TZ),
            fetcher=fetcher,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["written"], 0)
        self.assertEqual(
            [attempt["reason"] for attempt in result["attempts"]],
            [
                "previous_day_already_stored",
                "current_day_already_stored",
            ],
        )
        fetcher.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
