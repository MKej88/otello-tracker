"""Offline regression tests for bounded manual-refresh diagnostic grace."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from full_refresh_diagnostic import (
    MANUAL_GRACE, manual_refresh_grace, plausible_legacy_recovery, refresh_kind,
)
from production_diagnostic_policy import diagnostic_severity
from production_monitor import assess_production, expected_nightly_date

NOW = datetime(2026, 11, 22, 12, 44, tzinfo=UTC)
TARGET = expected_nightly_date(NOW).isoformat()
WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/cloudflare-workflow-diagnostics.yml"


def job(status="SUCCESS", *, start_minutes=360, finish_minutes=355, trigger="worker_cron:35 3 * * *",
        target=TARGET, error_message=None):
    return {
        "status": status,
        "started_at": (NOW - timedelta(minutes=start_minutes)).isoformat(),
        "finished_at": (NOW - timedelta(minutes=finish_minutes)).isoformat() if finish_minutes is not None else None,
        "error_message": error_message,
        "metadata_json": json.dumps({"trigger": trigger, "target_date": target}),
    }


class ManualGraceTests(unittest.TestCase):
    def test_recent_explicit_manual_with_immediately_prior_success(self):
        current = job("RUNNING", start_minutes=4, finish_minutes=None,
                      trigger="github_actions_manual_repair")
        previous = job(start_minutes=20, finish_minutes=18)
        result = manual_refresh_grace([current, previous], now=NOW, expected_target=TARGET)
        self.assertTrue(result["under_grace"])
        self.assertIs(result["previous"], previous)
        self.assertEqual(result["age_minutes"], 4)
        self.assertEqual(result["reason"], "recent_manual_running")

    def test_expired_manual_and_stale_previous_never_get_grace(self):
        prev = job(start_minutes=40, finish_minutes=38)
        for latest in [
            job("RUNNING", start_minutes=16, finish_minutes=None,
                trigger="github_actions_manual_repair"),
            job("RUNNING", start_minutes=-1, finish_minutes=None,
                trigger="github_actions_manual_repair"),
            job("RUNNING", start_minutes=4, finish_minutes=1,
                trigger="github_actions_manual_repair"),
            job("RUNNING", start_minutes=4, finish_minutes=None,
                trigger="worker_cron:35 3 * * *"),
            job("RUNNING", start_minutes=4, finish_minutes=None,
                trigger="untrusted-free-form"),
            job("FAILED", start_minutes=4, finish_minutes=2,
                trigger="github_actions_manual_repair"),
        ]:
            with self.subTest(status=latest["status"], metadata=latest["metadata_json"],
                              started=latest["started_at"]):
                self.assertFalse(manual_refresh_grace(
                    [latest, prev], now=NOW, expected_target=TARGET
                )["under_grace"])

    def test_previous_must_be_immediate_success_and_same_target(self):
        manual = job("RUNNING", start_minutes=4, finish_minutes=None,
                     trigger="github_actions_manual_repair")
        for previous in [
            job("FAILED", start_minutes=20, finish_minutes=18),
            job("PARTIAL", start_minutes=20, finish_minutes=18),
            job(start_minutes=20, finish_minutes=18, error_message="failed source"),
            job(start_minutes=20, finish_minutes=18, target="2026-11-20"),
            job(start_minutes=40, finish_minutes=None),
            job(start_minutes=40, finish_minutes=2),
        ]:
            with self.subTest(previous=previous):
                self.assertFalse(manual_refresh_grace(
                    [manual, previous], now=NOW, expected_target=TARGET
                )["under_grace"])

    def test_missing_untrusted_or_invalid_timestamps_fail_closed(self):
        good = job(start_minutes=20, finish_minutes=18)
        running = job("RUNNING", start_minutes=4, finish_minutes=None,
                      trigger="github_actions_manual_repair")
        for value in ["not-a-date", "2026-11-22T12:40:00", None]:
            self.assertFalse(manual_refresh_grace(
                [{**running, "started_at": value}, good],
                now=NOW, expected_target=TARGET
            )["under_grace"])
        self.assertFalse(manual_refresh_grace(
            [{**running, "metadata_json": "{malformed"}, good],
            now=NOW, expected_target=TARGET
        )["under_grace"])
        self.assertFalse(manual_refresh_grace(
            [running, good], now=NOW, expected_target="2026-11-20"
        )["under_grace"])

    def test_grace_does_not_hide_market_nav_or_source_failures(self):
        base = dict(
            full_status="SUCCESS", fast_status="SUCCESS", fast_severity="OK",
            fresh=True, monitoring_unhealthy=False,
            nav_audit_unhealthy=False, core_nav_status="BACKFILLED",
            secondary_bemobi_warning=False, manual_full_refresh_pending=True,
        )
        self.assertEqual(diagnostic_severity(**base), "ADVARSEL")
        # A stale or unverified Bemobi IR feed is still critical unless the
        # existing strict last-good/source policy explicitly validates it.
        self.assertEqual(
            diagnostic_severity(**{**base, "monitoring_unhealthy": True}),
            "AVVIK",
        )
        for patch in [
            {"monitoring_unhealthy": True},
            {"nav_audit_unhealthy": True},
            {"fast_severity": "FAILURE"},
            {"fresh": False},
            {"core_nav_status": "INVALID"},
        ]:
            self.assertEqual(diagnostic_severity(**{**base, **patch}), "AVVIK")


class ScheduledVsManualTests(unittest.TestCase):
    def test_explicit_manual_or_legacy_off_window_not_double_nightly(self):
        scheduled = job(start_minutes=549, finish_minutes=540)
        manual = job(start_minutes=20, finish_minutes=17,
                     trigger="github_actions_manual_repair")
        old_manual = job(start_minutes=278, finish_minutes=269, trigger=None)
        self.assertEqual(refresh_kind(scheduled), "scheduled")
        self.assertEqual(refresh_kind(manual), "manual")
        self.assertEqual(refresh_kind(old_manual), "legacy_outside_window")
        self.assertTrue(plausible_legacy_recovery(
            old_manual, now=NOW, target_date=TARGET
        ))
        self.assertFalse(plausible_legacy_recovery(
            old_manual, now=NOW, target_date="2026-11-22"
        ))

    def test_two_actual_scheduled_nightlies_still_count_as_duplicate(self):
        t = TARGET
        jobs = [
            job(start_minutes=549, finish_minutes=540),
            job(start_minutes=545, finish_minutes=530),
            job(start_minutes=20, finish_minutes=16, trigger="github_actions_manual_repair"),
        ]
        sources = [
            {"code": code, "status": "OK", "checked_at": NOW.isoformat()}
            for code in (
                "NORGES_BANK", "YAHOO_FINANCE", "B3", "CVM",
                "BEMOBI_IR", "NEWSWEB", "EURONEXT",
            )
        ]
        prices = [{"symbol": key, "data_date": t} for key in ("OTEC", "BMOB3", "LIF")]
        states = [
            {"key": "bemobi_official_news_v1",
             "value": json.dumps({"checked_date": t}), "updated_at": NOW.isoformat()},
            {"key": "cvm_ipe_archive_freshness",
             "value": json.dumps({"checked_date": t, "data_date": t}),
             "updated_at": NOW.isoformat()},
        ]
        good = assess_production(
            now=NOW, jobs=[jobs[0], jobs[2]], sources=sources,
            prices=prices, states=states,
        )
        duplicate = assess_production(
            now=NOW, jobs=jobs, sources=sources,
            prices=prices, states=states,
        )
        def double_check(result):
            return next(c for c in result["checks"] if c["name"] == "Ingen dobbel nattkjøring")
        self.assertEqual(double_check(good)["state"], "OK")
        self.assertEqual(double_check(duplicate)["state"], "AVVIK")


class WorkflowWiringTests(unittest.TestCase):
    def test_scheduled_incident_not_closed_while_manual_refresh_pending(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("manual_refresh_grace(", text)
        self.assertIn('manual_full_refresh_pending=manual_window["under_grace"]', text)
        self.assertIn("incident_deferred:", text)
        self.assertIn("needs.diagnose.result == 'success'", text)
        self.assertIn("needs.diagnose.outputs.incident_deferred == 'true'", text)
        self.assertIn("d1_deferred=", text)


if __name__ == "__main__":
    unittest.main()
