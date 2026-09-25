from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

import scheduled  # noqa: E402


class _Repository:
    def __init__(self) -> None:
        self.finished_status: str | None = None

    async def start_job(self, **kwargs: object) -> int:
        return 42

    async def finish_job(self, *args: object, **kwargs: object) -> None:
        self.finished_status = str(kwargs["status"])

    def performance_metrics(self) -> dict[str, object]:
        return {}


class ScheduledOtecActivityStatusTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_expected_activity_makes_job_partial(self) -> None:
        repository = _Repository()
        successful_step = AsyncMock(return_value={"status": "ok"})
        missing_activity = AsyncMock(
            return_value={"status": "no_trade", "written": 0, "attempts": []}
        )
        patches = (
            patch.object(
                scheduled, "PerformanceD1WriteRepository", return_value=repository
            ),
            patch.object(scheduled, "refresh_otec_daily_activity", missing_activity),
            patch.object(scheduled, "maybe_finalize_bmob3_eod", successful_step),
            patch.object(scheduled, "refresh_bmob3_intraday_price", successful_step),
            patch.object(scheduled, "collect_newsweb_fast", successful_step),
            patch.object(
                scheduled,
                "sync_interest_income_anchors_from_report_result",
                successful_step,
            ),
            patch.object(scheduled, "repair_norges_bank_fx_if_stale", successful_step),
            patch.object(scheduled, "repair_life360_lif_if_stale", successful_step),
            patch.object(
                scheduled, "sync_confirmed_bemobi_distribution_cash", successful_step
            ),
            patch.object(scheduled, "refresh_dirty_nav_layers", successful_step),
            patch.object(scheduled, "refresh_dashboard_hot_snapshot", successful_step),
        )

        with ExitStack() as stack:
            for dependency_patch in patches:
                stack.enter_context(dependency_patch)
            result = await scheduled.run_fast_refresh(
                object(), scheduled_time_ms=1788055200000
            )

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(repository.finished_status, "PARTIAL")
        self.assertEqual(
            result["source_errors"],
            [
                {
                    "step": "otec_activity",
                    "error": (
                        "Euronext-aktivitet mangler for en forventet handelsdag; "
                        "status=no_trade"
                    ),
                    "error_type": "OtecActivityIncomplete",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
