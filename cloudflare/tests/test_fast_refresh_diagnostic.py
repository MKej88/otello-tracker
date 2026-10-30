"""Regression coverage for the read-only fast-refresh GitHub watchdog."""
from __future__ import annotations

import ast
import json
import textwrap
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fast_refresh_diagnostic import assess_fast_refresh

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


if __name__ == "__main__":
    unittest.main()
