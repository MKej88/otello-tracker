"""Offline safety tests for partial Cloudflare nightly refresh diagnostics."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from production_diagnostic_policy import (
    REQUIRED_SOURCE_CODES,
    diagnostic_severity,
    secondary_bemobi_warning_candidate,
)
from production_monitor import assess_production, expected_nightly_date


NOW = datetime(2026, 10, 20, 9, 32, tzinfo=UTC)
TARGET = expected_nightly_date(NOW).isoformat()


def valid_full():
    metadata = {
        "target_date": TARGET,
        "critical_errors": [],
        "preflight": {"status": "ok", "ready": True, "blockers": []},
        "nav": {"status": "ok"},
        "archive": {"status": "skipped"},
        "source_health": {code: ("DEGRADED" if code == "BEMOBI_IR" else "OK")
                          for code in REQUIRED_SOURCE_CODES},
        "sources": {
            "bemobi_web": {
                "status": "partial",
                "policy": "ownership-core-confirmed-last-good-preserved",
                "ir": {"status": "ok"},
                "distribution_cash": {"status": "ok"},
                "result_release": {"status": "not_available"},
            },
        },
    }
    return {
        "status": "PARTIAL", "error_message": None,
        "started_at": (NOW - timedelta(hours=6)).isoformat(),
        "metadata_json": json.dumps(metadata),
    }


def sources():
    return [
        {
            "code": code, "checked_at": (NOW - timedelta(hours=6)).isoformat(),
            "status": "DEGRADED" if code == "BEMOBI_IR" else "OK",
        }
        for code in REQUIRED_SOURCE_CODES
    ]


def changed(full, path, value):
    result = dict(full)
    metadata = json.loads(full["metadata_json"])
    target = metadata
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    result["metadata_json"] = json.dumps(metadata)
    return result


class WarningCandidateTests(unittest.TestCase):
    def test_fallback_is_explicit_and_last_good_fact_policy_is_recorded(self):
        self.assertTrue(secondary_bemobi_warning_candidate(
            full=valid_full(), sources=sources(), expected_target=TARGET))

    def test_missing_metadata_and_missing_target_do_not_become_warning(self):
        full = valid_full()
        self.assertFalse(secondary_bemobi_warning_candidate(
            full={**full, "metadata_json": "{}"},
            sources=sources(), expected_target=TARGET))
        self.assertFalse(secondary_bemobi_warning_candidate(
            full=full, sources=sources(), expected_target="2026-10-18"))

    def test_critical_nav_or_preflight_failure_remains_fatal(self):
        for path, value in [
            (["nav", "status"], "partial"),
            (["preflight", "ready"], False),
            (["critical_errors"], [{"step": "nav", "error": "missing"}]),
            (["archive", "status"], "error"),
        ]:
            with self.subTest(path=path):
                self.assertFalse(secondary_bemobi_warning_candidate(
                    full=changed(valid_full(), path, value),
                    sources=sources(), expected_target=TARGET))

    def test_bad_official_ir_and_distribution_data_remain_critical(self):
        for path, value in [
            (["sources", "bemobi_web", "ir", "status"], "not_available"),
            (["sources", "bemobi_web", "distribution_cash", "status"], "error"),
            (["sources", "bemobi_web", "policy"], "not-validated"),
        ]:
            with self.subTest(path=path):
                self.assertFalse(secondary_bemobi_warning_candidate(
                    full=changed(valid_full(), path, value),
                    sources=sources(), expected_target=TARGET))

    def test_additional_failed_sources_or_error_message_do_not_get_exception(self):
        full = valid_full()
        bad_source = sources()
        for row in bad_source:
            if row["code"] == "NORGES_BANK":
                row["status"] = "DEGRADED"
        self.assertFalse(secondary_bemobi_warning_candidate(
            full=full, sources=bad_source, expected_target=TARGET))
        self.assertFalse(secondary_bemobi_warning_candidate(
            full={**full, "error_message": "failed to archive data"},
            sources=sources(), expected_target=TARGET))
        self.assertFalse(secondary_bemobi_warning_candidate(
            full={**full, "status": "FAILED"},
            sources=sources(), expected_target=TARGET))


class SeverityTests(unittest.TestCase):
    def test_secondary_source_and_estimated_core_nav_can_be_warning(self):
        self.assertEqual(diagnostic_severity(
            full_status="PARTIAL", fast_status="SUCCESS",
            fresh=True, monitoring_unhealthy=False,
            nav_audit_unhealthy=False, secondary_bemobi_warning=True,
            core_nav_status="DEGRADED"), "ADVARSEL")

    def test_primary_or_stale_data_still_fails(self):
        base = dict(
            full_status="PARTIAL", fast_status="SUCCESS",
            fresh=True, monitoring_unhealthy=False,
            nav_audit_unhealthy=False, secondary_bemobi_warning=True,
            core_nav_status="DEGRADED",
        )
        for key, value in [
            ("fresh", False), ("monitoring_unhealthy", True),
            ("nav_audit_unhealthy", True), ("fast_status", "FAILED"),
            ("full_status", "FAILED"), ("core_nav_status", "INVALID"),
            ("secondary_bemobi_warning", False),
        ]:
            with self.subTest(key=key):
                self.assertEqual(diagnostic_severity(**{**base, key: value}), "AVVIK")

    def test_all_healthy_is_green(self):
        self.assertEqual(diagnostic_severity(
            full_status="SUCCESS", fast_status="SUCCESS",
            fresh=True, monitoring_unhealthy=False,
            nav_audit_unhealthy=False, secondary_bemobi_warning=False,
            core_nav_status="BACKFILLED"), "OK")


class MonitoringTests(unittest.TestCase):
    def kwargs(self):
        job = valid_full()
        return dict(
            now=NOW,
            jobs=[job],
            sources=sources(),
            prices=[
                {"symbol": "OTEC", "data_date": TARGET},
                {"symbol": "BMOB3", "data_date": TARGET},
                {"symbol": "LIF", "data_date": TARGET},
            ],
            states=[
                {
                    "key": "bemobi_official_news_v1",
                    "value": json.dumps({"checked_date": TARGET}),
                    "updated_at": (NOW - timedelta(hours=5)).isoformat(),
                },
                {
                    "key": "cvm_ipe_archive_freshness",
                    "value": json.dumps({"checked_date": TARGET, "data_date": TARGET}),
                    "updated_at": (NOW - timedelta(hours=5)).isoformat(),
                },
            ],
        )

    def test_warning_is_reported_but_not_unhealthy(self):
        actual = assess_production(**self.kwargs(), allow_secondary_bemobi_warning=True)
        self.assertFalse(actual["unhealthy"])
        self.assertEqual(
            {x["name"] for x in actual["warnings"]},
            {"Nattkjøring ferdig", "Kildekontakt: BEMOBI_IR"},
        )

    def test_unchanged_strict_monitor_behavior_remains_default(self):
        actual = assess_production(**self.kwargs())
        self.assertTrue(actual["unhealthy"])
        self.assertFalse(actual["warnings"])

    def test_market_data_failure_overrides_secondary_warning(self):
        args = self.kwargs()
        args["prices"] = [row for row in args["prices"] if row["symbol"] != "BMOB3"]
        actual = assess_production(**args, allow_secondary_bemobi_warning=True)
        self.assertTrue(actual["unhealthy"])
        self.assertTrue(any(
            x["state"] == "AVVIK" and x["name"] == "Sluttkurs: BMOB3"
            for x in actual["checks"]
        ))

    def test_missing_or_stale_secondary_source_cannot_be_ignored(self):
        args = self.kwargs()
        for row in args["sources"]:
            if row["code"] == "BEMOBI_IR":
                row["checked_at"] = (NOW - timedelta(days=3)).isoformat()
        actual = assess_production(**args, allow_secondary_bemobi_warning=True)
        self.assertTrue(actual["unhealthy"])

    def test_two_partial_night_jobs_are_not_silently_accepted(self):
        args = self.kwargs()
        args["jobs"].append({**args["jobs"][0], "started_at": (NOW - timedelta(hours=5)).isoformat()})
        actual = assess_production(**args, allow_secondary_bemobi_warning=True)
        self.assertTrue(actual["unhealthy"])


if __name__ == "__main__":
    unittest.main()



class CvmWeeklyFreshnessTests(unittest.TestCase):
    def test_week_old_archive_is_fresh_but_old_archive_warns(self):
        from cvm_freshness import CVM_IPE_MAX_AGE_DAYS

        self.assertEqual(CVM_IPE_MAX_AGE_DAYS, 10)
        for now, expected in [
            (datetime(2026, 10, 24, 9, 30, tzinfo=UTC), "OK"),
            (datetime(2026, 10, 30, 9, 30, tzinfo=UTC), "AVVIK"),
        ]:
            with self.subTest(now=now):
                target = expected_nightly_date(now).isoformat()
                data = MonitoringTests().kwargs()
                data["now"] = now
                data["states"][1]["value"] = json.dumps({
                    "checked_date": target, "data_date": "2026-10-18",
                })
                data["states"][1]["updated_at"] = now.isoformat()
                actual = assess_production(**data)
                cvm = next(check for check in actual["checks"]
                           if check["name"] == "CVM-filens datadato")
                self.assertEqual(cvm["state"], expected)
