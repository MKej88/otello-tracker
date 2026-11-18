from __future__ import annotations

import asyncio
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bemobi_after_oslo as after_oslo  # noqa: E402
import repository as repository_module  # noqa: E402
import scheduled  # noqa: E402


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FakeRepository:
    def __init__(self) -> None:
        self.writes = []
        self.finished = None

    async def run(self, statement, parameters=()):
        self.writes.append((statement, parameters))

    async def start_job(self, **kwargs):
        return 7

    async def finish_job(self, job_id, **kwargs):
        self.finished = kwargs


async def ready(_repo, *, now):
    return {"status": "ready", "ready": True, "fx_movement": {"ready": True}}


async def missing(_repo, *, now):
    return {"status": "missing_reference", "ready": False, "fx_movement": {"ready": False}}


async def recover_ok(_repo, *, now):
    return {"status": "ok"}


async def refresh_ok(*args, **kwargs):
    return {"status": "ok"}


class PostCloseRefreshTests(unittest.TestCase):
    def run_job(self, now: str, *, card=ready, error=False):
        repo = FakeRepository()

        async def provider_error(*args, **kwargs):
            raise RuntimeError("upstream secret must not enter metadata")

        with (
            patch.object(repository_module, "D1WriteRepository", return_value=repo),
            patch.object(after_oslo, "bemobi_after_oslo", new=card),
            patch.object(scheduled, "recover_reference", new=recover_ok),
            patch.object(scheduled, "recover_fx_close_reference", new=recover_ok),
            patch.object(scheduled, "refresh_bmob3_intraday_price", new=provider_error if error else refresh_ok),
            patch.object(scheduled, "refresh_exchangerate_dev_brl_nok", new=refresh_ok),
        ):
            result = asyncio.run(scheduled.run_after_oslo_close_refresh(
                object(), now=dt(now), exr_enabled=True, exr_license_approved=True,
            ))
        return result, repo

    def test_runs_for_winter_and_summer_after_close(self):
        for now in ("2026-11-18T15:47:00Z", "2026-07-08T14:47:00Z",
                    "2026-04-01T11:27:00Z"):
            with self.subTest(now=now):
                result, repo = self.run_job(now)
                self.assertEqual(result["status"], "SUCCESS")
                self.assertTrue(repo.finished)
                self.assertEqual(repo.finished["records_written"], 2)
                self.assertTrue(repo.writes)
                self.assertEqual(result["card_status"], "ready")

    def test_wrong_dst_hour_before_window_and_holidays_do_not_fetch(self):
        for now in ("2026-11-18T14:47:00Z", "2026-07-08T15:47:00Z",
                    "2026-11-18T15:36:00Z", "2026-11-21T15:47:00Z",
                    "2026-12-25T15:47:00Z"):
            with self.subTest(now=now):
                result, repo = self.run_job(now)
                self.assertEqual(result["status"], "SKIPPED")
                self.assertEqual(repo.writes, [])

    def test_missing_reference_reports_partial_without_invented_quotes(self):
        result, repo = self.run_job("2026-11-18T15:47:00Z", card=missing)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["card_status"], "missing_reference")
        self.assertEqual(repo.finished["status"], "PARTIAL")

    def test_provider_failure_is_sanitized_and_other_sources_still_run(self):
        result, repo = self.run_job("2026-11-18T15:47:00Z", card=missing, error=True)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["steps"]["bemobi_quote"],
                         {"status": "error", "error_type": "RuntimeError"})
        self.assertEqual(result["steps"]["fx_quote"]["status"], "ok")
        self.assertNotIn("secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
