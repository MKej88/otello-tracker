from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nightly_trigger import ensure_nightly_refresh, nightly_is_overdue


class Repository:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE job_runs (id INTEGER PRIMARY KEY, job_name TEXT, status TEXT, metadata_json TEXT)"
        )

    def add(self, status, target):
        self.db.execute(
            "INSERT INTO job_runs(job_name,status,metadata_json) VALUES (?,?,?)",
            ("cloudflare_full_refresh", status, json.dumps({"target_date": target})),
        )

    async def first(self, sql, parameters):
        row = self.db.execute(sql, parameters).fetchone()
        return dict(row) if row else None


class NightlyTriggerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = Repository()
        self.workflow = SimpleNamespace(create=AsyncMock(), get=AsyncMock())
        self.now = datetime(2026, 9, 29, 4, 0, tzinfo=UTC)

    async def test_missing_run_recovers_previous_calendar_day(self):
        self.repo.add("SUCCESS", "2026-09-26")
        result = await ensure_nightly_refresh(self.repo, self.workflow, now=self.now)
        self.assertEqual(result["status"], "STARTED")
        self.workflow.create.assert_awaited_once_with(
            id="nightly-2026-09-28",
            params={"target_date": "2026-09-28", "trigger": "worker_cron:35 3 * * *"},
        )

    async def test_does_not_start_before_due(self):
        await ensure_nightly_refresh(
            self.repo, self.workflow, now=self.now.replace(hour=3, minute=34)
        )
        self.workflow.create.assert_not_awaited()

    async def test_success_or_running_native_instance_is_not_duplicated(self):
        for status in ["SUCCESS", "RUNNING"]:
            repo = Repository()
            repo.add(status, "2026-09-28")
            result = await ensure_nightly_refresh(repo, self.workflow, now=self.now)
            self.assertEqual(result["reason"], "already_recorded")
        self.workflow.create.assert_not_awaited()

    async def test_partial_run_allows_one_recovery(self):
        self.repo.add("PARTIAL", "2026-09-28")
        result = await ensure_nightly_refresh(self.repo, self.workflow, now=self.now)
        self.assertEqual(result["status"], "STARTED")

    async def test_duplicate_delivery_confirms_existing_instance(self):
        self.workflow.create.side_effect = RuntimeError("already exists")
        self.workflow.get.return_value = SimpleNamespace(
            status=AsyncMock(return_value={"status": "running"})
        )
        result = await ensure_nightly_refresh(self.repo, self.workflow, now=self.now)
        self.assertEqual(result["status"], "EXISTS")
        self.workflow.get.assert_awaited_once_with("nightly-2026-09-28")

    async def test_api_failure_is_not_reported_as_success(self):
        self.workflow.create.side_effect = RuntimeError("API unavailable")
        self.workflow.get.side_effect = RuntimeError("API unavailable")
        with self.assertRaisesRegex(RuntimeError, "API unavailable"):
            await ensure_nightly_refresh(self.repo, self.workflow, now=self.now)

    async def test_failed_existing_instance_is_not_restarted(self):
        self.workflow.create.side_effect = RuntimeError("already exists")
        self.workflow.get.return_value = SimpleNamespace(
            status=AsyncMock(return_value=SimpleNamespace(status="errored"))
        )
        with self.assertRaisesRegex(RuntimeError, "errored"):
            await ensure_nightly_refresh(self.repo, self.workflow, now=self.now)

    async def test_weekend_and_winter_use_same_utc_schedule(self):
        for now, target in [
            (datetime(2026, 9, 27, 3, 35, tzinfo=UTC), "2026-09-26"),
            (datetime(2026, 12, 1, 3, 35, tzinfo=UTC), "2026-11-30"),
        ]:
            result = await ensure_nightly_refresh(self.repo, self.workflow, now=now)
            self.assertEqual(result["target_date"], target)

    def test_missing_daily_run_is_stale_after_grace_even_under_36_hours(self):
        start = "2026-09-28T03:35:10Z"
        self.assertFalse(nightly_is_overdue(start, now=self.now.replace(minute=29)))
        self.assertTrue(nightly_is_overdue(start, now=self.now.replace(minute=30)))
        self.assertFalse(
            nightly_is_overdue("2026-09-29T03:35:10Z", now=self.now.replace(minute=30))
        )


if __name__ == "__main__":
    unittest.main()
