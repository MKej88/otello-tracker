from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import brazil_dashboard as base  # noqa: E402
import brazil_macro_resilience as macro  # noqa: E402
from brazil_investor_insights import TREND_STATE_KEY, build_focus_trend, build_investor_summary  # noqa: E402
from brazil_snapshot import STATE_KEY, save_snapshot  # noqa: E402
import brazil_snapshot as snapshot  # noqa: E402


class Repository:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE runtime_state(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")

    async def first(self, sql, params=()):
        row = self.db.execute(sql, params).fetchone()
        return dict(row) if row else None

    async def run(self, sql, params=()):
        self.db.execute(sql, params)


def focus(ref_date: str, median: float = 12) -> dict:
    return {
        "values": {
            key: {str(year): {"median": median, "survey_date": ref_date} for year in (2026, 2027)}
            for key in base.FOCUS_REQUIRED_KEYS
        },
        "focus_meta": {"ref_date": ref_date, "current_year": 2026},
    }


class BrazilSourceCacheTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repo = Repository()
        self.now = datetime(2026, 10, 9, 12, tzinfo=UTC)

    def tearDown(self) -> None:
        self.repo.db.close()

    def result(self, *, metrics=None, now=None):
        return {
            "as_of_date": "2026-10-09",
            "generated_at": (now or self.now).isoformat(),
            "metrics": metrics or {},
            "source_status": {key: {"ready": False, "error": "Upstream HTTP 503"} for key in base.SERIES},
        }

    async def seed_metrics(self):
        result = self.result(metrics={
            key: {"value": 0 if key == "ibc_services" else 15, "date": "2026-09-01", "source": "BCB SGS"}
            for key in base.SERIES
        })
        await macro.resolve_macro_metrics(self.repo, result)
        return result

    async def test_source_outage_restores_metrics_before_summary_calculation(self):
        await self.seed_metrics()
        result = self.result(metrics={"ibc_br": {"value": 1, "date": "2026-09-02"}})
        result["focus"] = focus("2026-10-08")
        await macro.resolve_macro_metrics(self.repo, result)
        summary = build_investor_summary(result, {})
        self.assertEqual(summary["rate_path"]["current"], 15)
        self.assertEqual(result["metrics"]["ibc_services"]["value"], 0)
        self.assertEqual(result["metrics"]["selic"]["date"], "2026-09-01")
        self.assertEqual(result["metrics"]["ibc_br"]["value"], 1)
        self.assertTrue(result["source_status"]["selic"]["fallback"])
        self.assertEqual(result["source_status"]["selic"]["error"], "Upstream HTTP 503")

    async def test_repeated_failures_do_not_renew_last_good_timestamp(self):
        await self.seed_metrics()
        outage = self.result(now=self.now + timedelta(days=6))
        await macro.resolve_macro_metrics(self.repo, outage)
        self.assertIn("selic", outage["metrics"])
        expired = self.result(now=self.now + timedelta(days=8))
        await macro.resolve_macro_metrics(self.repo, expired)
        self.assertEqual(expired["metrics"], {})

    async def test_older_concurrent_fetch_does_not_replace_newer_metric(self):
        await self.seed_metrics()
        older = self.result(metrics={"selic": {"value": 20, "date": "2026-08-01"}}, now=self.now + timedelta(minutes=1))
        await macro.resolve_macro_metrics(self.repo, older)
        outage = self.result(now=self.now + timedelta(minutes=2))
        await macro.resolve_macro_metrics(self.repo, outage)
        self.assertEqual(outage["metrics"]["selic"]["value"], 15)

    async def test_invalid_and_future_cache_is_not_displayed(self):
        for metric in ({"date": "2026-10-10", "value": 15}, {"date": "2026-09-01", "value": None}, {"date": "bad", "value": 15}):
            await self.repo.run("INSERT OR REPLACE INTO runtime_state VALUES (?, ?, ?)", (
                "brazil.macro.selic.v1", json.dumps({"metric": metric, "fetched_at": self.now.isoformat()}), self.now.isoformat()
            ))
            result = self.result()
            await macro.resolve_macro_metrics(self.repo, result)
            self.assertNotIn("selic", result["metrics"])

    async def test_database_failure_keeps_live_metrics(self):
        repo = AsyncMock()
        repo.run.side_effect = RuntimeError("D1 unavailable")
        repo.first.side_effect = RuntimeError("D1 unavailable")
        result = self.result(metrics={"selic": {"value": 15, "date": "2026-10-09"}})
        await macro.resolve_macro_metrics(repo, result)
        self.assertEqual(result["metrics"]["selic"]["value"], 15)
        self.assertIn("cache_error", result["source_status"]["selic"])

    async def test_historical_focus_outage_recomputes_changes_from_raw_cache(self):
        live = AsyncMock(side_effect=lambda target, **kwargs: focus(target))
        with patch.object(base, "_load_focus", live):
            await build_focus_trend(as_of_date="2026-10-09", current_focus=focus("2026-10-08"), repository=self.repo)
        with patch.object(base, "_load_focus", AsyncMock(side_effect=RuntimeError("HTTP 503"))):
            trend, status = await build_focus_trend(as_of_date="2026-10-09", current_focus=focus("2026-10-08", median=11), repository=self.repo)
        self.assertEqual(trend["comparisons"]["30d"]["points_by_year"]["2027"]["selic"]["change_bp"], -100)
        self.assertEqual(trend["comparisons"]["30d"]["ref_date"], "2026-09-08")
        self.assertEqual(status["cached_comparisons"], ["30d", "7d"])
        self.assertIn("30d", status["errors"])

    async def test_history_for_other_reference_date_is_not_reused(self):
        with patch.object(base, "_load_focus", AsyncMock(side_effect=lambda target, **kwargs: focus(target))):
            await build_focus_trend(as_of_date="2026-10-09", current_focus=focus("2026-10-08"), repository=self.repo)
        with patch.object(base, "_load_focus", AsyncMock(side_effect=RuntimeError("HTTP 503"))):
            trend, status = await build_focus_trend(as_of_date="2026-10-09", current_focus=focus("2026-10-09"), repository=self.repo)
        self.assertFalse(trend["comparisons"]["30d"]["ready"])
        self.assertFalse(status["fallback"])

    async def test_daily_refreshes_retain_both_monthly_and_weekly_history(self):
        with patch.object(base, "_load_focus", AsyncMock(side_effect=lambda target, **kwargs: focus(target))):
            for day in range(1, 7):
                ref_date = f"2026-10-{day:02d}"
                await build_focus_trend(as_of_date=ref_date, current_focus=focus(ref_date), repository=self.repo)
        stored = json.loads((await self.repo.first(
            "SELECT value FROM runtime_state WHERE key=?", (TREND_STATE_KEY,)
        ))["value"])
        self.assertEqual(len(stored), 8)
        with patch.object(base, "_load_focus", AsyncMock(side_effect=RuntimeError("HTTP 503"))):
            trend, status = await build_focus_trend(as_of_date="2026-10-06", current_focus=focus("2026-10-06"), repository=self.repo)
        self.assertTrue(trend["comparisons"]["30d"]["ready"])
        self.assertEqual(status["cached_comparisons"], ["30d", "7d"])

    async def test_snapshot_sql_preserves_complete_and_newer_responses(self):
        payload = self.result(metrics={key: {"value": 15} for key in (*base.SERIES, "brl_nok")})
        payload.update(ready=True, focus=focus("2026-10-08"), focus_trend={"comparisons": {"30d": {"points_by_year": {
            str(year): {key: {"change": 0} for key in ("selic", "ipca", "gdp")} for year in (2026, 2027)
        }}}})
        await save_snapshot(self.repo, payload)
        older = copy.deepcopy(payload)
        older["generated_at"] = (self.now - timedelta(minutes=1)).isoformat()
        older["metrics"]["selic"]["value"] = 20
        await save_snapshot(self.repo, older)
        await save_snapshot(self.repo, dict(payload, metrics={"brl_nok": {"value": 2}}))
        stored = json.loads((await self.repo.first("SELECT value FROM runtime_state WHERE key=?", (STATE_KEY,)))["value"])
        self.assertEqual(stored["metrics"]["selic"]["value"], 15)

    async def test_http_cache_does_not_keep_partial_or_fallback_responses(self):
        spec = importlib.util.spec_from_file_location(
            "brazil_http_cache_test_app", Path(__file__).resolve().parents[1] / "src/app.py"
        )
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
        complete = self.result(metrics={key: {"value": 15} for key in (*base.SERIES, "brl_nok")})
        complete.update(ready=True, focus=focus("2026-10-08"), focus_trend={"comparisons": {"30d": {"points_by_year": {
            str(year): {key: {"change": 0} for key in ("selic", "ipca", "gdp")} for year in (2026, 2027)
        }}}})
        payloads = [
            (complete, "public, max-age=300"),
            (dict(complete, metrics={"brl_nok": {"value": 2}}), "no-store"),
            (dict(complete, source_status={"selic": {"fallback": True}}), "no-store"),
        ]
        with TestClient(api.app) as client:
            for payload, expected in payloads:
                with patch.object(api, "_write_repository", return_value=self.repo), patch.object(
                    snapshot, "cached_brazil_dashboard", AsyncMock(return_value=payload)
                ):
                    response = client.get("/api/brazil/dashboard")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], expected)
                if expected == "no-store":
                    self.assertEqual(response.headers["cloudflare-cdn-cache-control"], "no-store")
            invalid = client.get("/api/brazil/dashboard?as_of_date=bad")
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.headers["cache-control"], "no-store")
