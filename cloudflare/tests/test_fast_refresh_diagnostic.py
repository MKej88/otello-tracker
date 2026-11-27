"""Regression coverage for the read-only fast-refresh GitHub watchdog."""
from __future__ import annotations

import ast
import json
import sqlite3
import textwrap
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fast_refresh_diagnostic import (assess_fast_refresh, assess_fast_refresh_window,
                                     public_fast_refresh_warning, TRANSLATION_ERROR_GROUPS_SQL,
                                     TRANSLATION_DOCUMENTS_SQL, render_translation_diagnostics)

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

    def test_translation_queue_warning_does_not_hide_nav_errors(self):
        item = record("PARTIAL", errors=[{"step": "bemobi_translation"}],
                      steps={"bemobi_translation": {"status": "partial", "non_critical": True},
                             "dirty_nav": {"status": "ok"}})
        self.assertEqual(self.assess(item)["severity"], "WARNING")
        item = record("PARTIAL", errors=[{"step": "bemobi_translation"}, {"step": "dirty_nav"}],
                      steps={"bemobi_translation": {"status": "partial", "non_critical": True},
                             "dirty_nav": {"status": "error"}})
        self.assertEqual(self.assess(item)["severity"], "FAILURE")

    def test_public_translation_warning_only_exposes_curated_counts(self):
        item = record("PARTIAL", errors=[{"step": "bemobi_translation", "error": "secret"}],
                      steps={"bemobi_translation": {"status": "partial", "non_critical": True,
                               "queue": {"failed": 9, "exhausted": 1, "overdue": 1, "secret": "private"},
                               "failed": 1}, "dirty_nav": {"status": "ok"}})
        self.assertEqual(public_fast_refresh_warning(item, now=NOW, max_age=timedelta(minutes=90)),
                         {"steps": ["bemobi_translation"], "translation_queue": {
                             "failed": 9, "exhausted": 1, "overdue": 1, "failed_this_run": 1}})
        metadata = json.loads(item["metadata_json"])
        metadata["source_errors"].append({"step": "dirty_nav"})
        item["metadata_json"] = json.dumps(metadata)
        self.assertIsNone(public_fast_refresh_warning(item, now=NOW, max_age=timedelta(minutes=90)))

    def test_translation_error_groups_expose_categories_not_raw_messages(self):
        db = sqlite3.connect(":memory:")
        db.executescript("""
            CREATE TABLE sources(id INTEGER, code TEXT);
            INSERT INTO sources VALUES (1, 'CVM'), (2, 'OTHER');
            CREATE TABLE source_documents(source_id INTEGER, translation_status TEXT,
                                          translation_attempts INTEGER, translation_error TEXT);
            INSERT INTO source_documents VALUES
              (1, 'FAILED', 3, 'verdikontroll feilet (2 mangler)'),
              (1, 'PENDING', 1, 'originaldokument HTTP 429'),
              (1, 'FAILED', 2, 'secret URL'),
              (1, 'READY', 1, 'secret'),
              (2, 'FAILED', 3, 'secret');
        """)
        self.assertEqual(db.execute(TRANSLATION_ERROR_GROUPS_SQL).fetchall(),
                         [("document_http", 1, 0), ("other", 1, 0), ("value_validation", 1, 1)])
        db.close()

    def test_document_diagnostic_never_exposes_raw_errors(self):
        db = sqlite3.connect(":memory:")
        db.executescript("""
            CREATE TABLE sources(id INTEGER, code TEXT);
            INSERT INTO sources VALUES (1, 'CVM'), (2, 'OTHER');
            CREATE TABLE source_documents(id INTEGER, source_id INTEGER, translation_status TEXT,
                                          translation_attempts INTEGER, translation_error TEXT);
            INSERT INTO source_documents VALUES
              (1, 1, 'FAILED', 3, 'originaldokument HTTP 526 secret URL'),
              (2, 1, 'FAILED', 1, 'translation:WorkersAIError: ai_category=quota; ai_code=3036; ai_http=429 secret'),
              (3, 2, 'FAILED', 3, 'secret');
        """)
        db.row_factory = sqlite3.Row
        unresolved = [dict(row) for row in db.execute(TRANSLATION_DOCUMENTS_SQL)]
        self.assertEqual(unresolved[1]["http"], 526)
        self.assertEqual(unresolved[0]["stage"], "translation")
        self.assertEqual(unresolved[0]["ai_code"], 3036)
        self.assertEqual(len(unresolved), 2)
        item = record("PARTIAL", steps={"bemobi_translation": {
            "model": "@cf/google/gemma-4-26b-a4b-it",
            "ai_probe": {"status": "error", "binding_calls": 1,
                         "error": {"category": "quota", "code": 3036, "http": 429, "message": "secret"}},
            "diagnostics": [{
                "document_id": 2, "source": "CVM", "stage": "translation", "outcome": "error",
                "native_binding": True, "ai_provider_calls": 1, "ai_binding_calls": 1, "ai_responses": 0,
                "downloads": [{"route": "original", "result": "http_error", "http": 526, "url": "secret"},
                              {"route": "official_alternative", "result": "ok", "http": 200}],
            }]}})
        rendered = "\n".join(render_translation_diagnostics(item, unresolved))
        self.assertIn("HTTP 526", rendered)
        self.assertIn("official_alternative: ok (HTTP 200)", rendered)
        self.assertIn("1 / 1 / 0", rendered)
        self.assertIn("gemma-4", rendered)
        self.assertIn("AI-produksjonstest: error", rendered)
        self.assertIn("kode 3036 / HTTP 429", rendered)
        self.assertNotIn("secret", rendered)
        self.assertIn("eldre kjøring", "\n".join(render_translation_diagnostics(
            record(steps={"bemobi_translation": {"model": "secret"}}), [])))
        db.close()

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
