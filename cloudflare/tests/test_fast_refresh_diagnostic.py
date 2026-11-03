"""Regression coverage for the read-only fast-refresh GitHub watchdog."""
from __future__ import annotations

import ast
import json
import textwrap
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fast_refresh_diagnostic import assess_fast_refresh, assess_fast_refresh_window

NOW = datetime(2026, 10, 30, 0, 55, tzinfo=UTC)
WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/cloudflare-workflow-diagnostics.yml"


def record(status="SUCCESS", minutes=24, errors=None, steps=None):
    metadata = {"source_errors": errors or [], "steps": steps or {}}
    return {
        "status": status,
        "finished_at": (NOW - timedelta(minutes=minutes)).isoformat(),
        "metadata_json": json.dumps(metadata),
    }


class FastRefreshDiagnosticTests(unittest.TestCase):
    def assess(self, item):
        return assess_fast_refresh(item, now=NOW)

    def test_healthy_success(self):
        self.assertEqual(self.assess(record())["severity"], "OK")

    def test_partial_otec_failure_is_critical_and_identifies_step(self):
        item = record("PARTIAL", errors=[{
            "step": "otec_activity", "error_type": "OtecActivityIncomplete",
            "error": "provider might include a secret",
        }], steps={"otec_activity": {"status": "partial"}})
        result = self.assess(item)
        self.assertEqual(result["severity"], "FAILURE")
        self.assertEqual(result["steps"][0], {
            "step": "otec_activity",
            "type": "OtecActivityIncomplete",
            "status": "partial",
        })
        self.assertNotIn("secret", json.dumps(result))

    def test_unknown_step_cannot_mark_itself_as_noncritical(self):
        item = record("PARTIAL", errors=[{"step": "dirty_nav"}], steps={
            "dirty_nav": {"status": "ok", "non_critical": True},
        })
        self.assertEqual(self.assess(item)["severity"], "FAILURE")

    def test_only_explicit_known_noncritical_failure_warns(self):
        item = record("PARTIAL", errors=[
            {"step": "brazil_snapshot", "error_type": "TimeoutError"},
        ], steps={"brazil_snapshot": {"non_critical": True, "status": "error"},
                  "dirty_nav": {"status": "ok"}})
        self.assertEqual(self.assess(item)["severity"], "WARNING")
        item["metadata_json"] = json.dumps({
            "source_errors": [
                {"step": "brazil_snapshot"}, {"step": "newsweb_history"},
            ],
            "steps": {"brazil_snapshot": {"non_critical": True},
                      "dirty_nav": {"status": "ok"}},
        })
        self.assertEqual(self.assess(item)["severity"], "FAILURE")

    def test_missing_valid_nav_keeps_partial_critical(self):
        item = record("PARTIAL", errors=[{"step": "brazil_snapshot"}],
                      steps={"brazil_snapshot": {"non_critical": True}})
        self.assertEqual(self.assess(item)["severity"], "FAILURE")

    def test_partial_without_metadata_is_critical(self):
        item = record("PARTIAL")
        item["metadata_json"] = "{invalid"
        self.assertEqual(self.assess(item)["severity"], "FAILURE")

    def test_stale_success_and_future_timestamp_fail(self):
        self.assertEqual(self.assess(record(minutes=101))["severity"], "FAILURE")
        self.assertEqual(self.assess(record(minutes=-1))["severity"], "FAILURE")

    def test_failed_refresh_still_critical(self):
        self.assertEqual(self.assess(record("FAILED"))["severity"], "FAILURE")

    def test_success_with_errors_is_inconsistent(self):
        item = record(errors=[{"step": "bmob3_intraday"}])
        self.assertEqual(self.assess(item)["severity"], "FAILURE")

    def test_untrusted_codes_never_reach_diagnostic_log(self):
        item = record("PARTIAL", errors=[
            {"step": "x\n::notice::injection", "error_type": "token=abc123"},
        ])
        report = self.assess(item)
        self.assertEqual(report["steps"][0]["step"], "unknown")
        self.assertEqual(report["steps"][0]["type"], "unknown")

    def test_invalid_timestamps_fail_closed(self):
        for time_value in (None, "not-a-date", "2026-10-30T00:35:00"):
            with self.subTest(time_value=time_value):
                item = record()
                item["finished_at"] = time_value
                item["started_at"] = None
                self.assertEqual(self.assess(item)["severity"], "FAILURE")

    def test_real_watchdog_script_is_parseable_and_reads_metadata(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        section = content.split("      - name: Verify latest 30-minute refresh", 1)[1]
        script = section.split("          python - <<'PY'\n", 1)[1]
        # The first inline Python block builds the D1 query.
        script = script.split("\n          PY", 1)[0]
        ast.parse(textwrap.dedent(script))
        self.assertIn("metadata_json", script)
        self.assertIn("fast_refresh_diagnostic", content)


class RunningRefreshTests(unittest.TestCase):
    def test_issue_869_recent_running_with_previous_success_is_warning(self):
        latest = {"status": "RUNNING", "started_at": (NOW - timedelta(minutes=8)).isoformat(),
                  "finished_at": None}
        result = assess_fast_refresh_window([latest, record(minutes=38)], now=NOW)
        self.assertEqual(result["severity"], "WARNING")
        self.assertEqual(result["reason"], "recent_running_with_healthy_previous")
        self.assertEqual(result["previous_status"], "SUCCESS")
        self.assertEqual(result["previous_age_minutes"], 38)

    def test_running_after_grace_is_critical_even_with_recent_success(self):
        latest = {"status": "RUNNING", "started_at": (NOW - timedelta(minutes=11)).isoformat()}
        self.assertEqual(
            assess_fast_refresh_window([latest, record(minutes=41)], now=NOW)["reason"],
            "running_exceeded_grace",
        )

    def test_running_requires_healthy_recent_completed_job(self):
        latest = {"status": "RUNNING", "started_at": (NOW - timedelta(minutes=3)).isoformat()}
        for rows in (
            [latest],
            [latest, record("FAILED")],
            [latest, record(minutes=101)],
            [latest, record("PARTIAL")],
        ):
            with self.subTest(rows=rows):
                self.assertEqual(assess_fast_refresh_window(rows, now=NOW)["severity"], "FAILURE")

    def test_running_never_skips_failed_completed_job(self):
        latest = {"status": "RUNNING", "started_at": (NOW - timedelta(minutes=3)).isoformat()}
        rows = [latest, record("FAILED", minutes=35), record(minutes=65)]
        self.assertEqual(assess_fast_refresh_window(rows, now=NOW)["severity"], "FAILURE")

    def test_running_rejects_future_or_invalid_start_and_inconsistent_finish(self):
        for start, finish in (
            ((NOW + timedelta(minutes=1)).isoformat(), None),
            ("not-a-date", None),
            (NOW.isoformat(), NOW.isoformat()),
        ):
            with self.subTest(start=start):
                rows = [{"status": "RUNNING", "started_at": start, "finished_at": finish},
                        record(minutes=35)]
                self.assertEqual(assess_fast_refresh_window(rows, now=NOW)["severity"], "FAILURE")

    def test_completed_failure_and_unclassified_partial_remain_critical(self):
        for latest in (record("FAILED"), record("PARTIAL"), record("UNKNOWN")):
            with self.subTest(latest=latest["status"]):
                self.assertEqual(
                    assess_fast_refresh_window([latest, record(minutes=45)], now=NOW)["severity"],
                    "FAILURE",
                )

    def test_watchdog_and_nightly_both_use_window_evaluation(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("assess_fast_refresh_window(fast_rows", content)
        self.assertIn("report = assess_fast_refresh_window(rows)", content)
        self.assertIn("previous_age_minutes", content)
        self.assertIn("fast_severity=fast_report['severity']", content)


if __name__ == "__main__":
    unittest.main()
