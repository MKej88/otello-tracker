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
    async def start_job(self, **kwargs: object) -> int:
        return 42

    async def finish_job(self, *args: object, **kwargs: object) -> None:
        return None

    def performance_metrics(self) -> dict[str, object]:
        return {}


class ScheduledLockRenewalTest(unittest.IsolatedAsyncioTestCase):
    async def test_renews_lock_at_each_checkpoint_in_order(self) -> None:
        renew_lock = AsyncMock()
        successful_step = AsyncMock(return_value={"status": "ok"})
        patches = (
            patch.object(
                scheduled, "PerformanceD1WriteRepository", return_value=_Repository()
            ),
            patch.object(scheduled, "refresh_otec_daily_activity", successful_step),
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
                object(),
                scheduled_time_ms=1788055200000,
                renew_lock=renew_lock,
            )
            result_without_lock = await scheduled.run_fast_refresh(
                object(),
                scheduled_time_ms=1788055200000,
            )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result_without_lock["status"], "SUCCESS")
        self.assertEqual(
            [call.args[0] for call in renew_lock.await_args_list],
            [
                "after OTEC",
                "after B3",
                "after NewsWeb",
                "after Otello reports",
                "after Norges Bank FX",
                "after Life360 LIF repair",
                "after Bemobi distribution cash",
                "after dirty NAV",
                "after dashboard snapshot",
            ],
        )


if __name__ == "__main__":
    unittest.main()
