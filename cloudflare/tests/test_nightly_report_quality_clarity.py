import unittest

from status_email_report import operational_lines
from nav_quality_policy import expected_dashboard_quality


class NightlyReportQualityClarityTests(unittest.TestCase):
    def test_quality_warning_preserves_status_and_other_incidents(self):
        lines, count = operational_lines({
            "status": "SUCCESS",
            "preflight": {"warnings": [{
                "name": "dashboard_quality",
                "details": {
                    "data_status": "DEGRADED",
                    "quality_notes": "FULL NAV methodology " * 100,
                },
            }]},
            "source_results": {"bemobi_web": {"status": "partial"}},
            "source_health": {"BEMOBI_IR": "DEGRADED"},
        })
        report = "\n".join(lines)
        self.assertEqual(count, 3)
        self.assertIn("NAV-datakvalitet DEGRADED", report)
        self.assertNotIn("FULL NAV methodology", report)
        self.assertIn("bemobi_web", report)
        self.assertIn("BEMOBI_IR", report)


    def test_expected_model_requires_evidence_and_critical_checks(self):
        expected = {"data_status": "DEGRADED", "cash_quality": "FORECAST_PARTIAL"}
        self.assertTrue(expected_dashboard_quality(expected, critical_checks_passed=True))
        self.assertFalse(expected_dashboard_quality(expected, critical_checks_passed=False))
        self.assertFalse(expected_dashboard_quality({"data_status": "DEGRADED"}, critical_checks_passed=True))
        self.assertFalse(expected_dashboard_quality({"data_status": "ESTIMATED"}, critical_checks_passed=True))
        self.assertFalse(expected_dashboard_quality(
            {**expected, "receivable_quality": "ESTIMATED_GROSS"}, critical_checks_passed=True))
        self.assertFalse(expected_dashboard_quality(
            {**expected, "market_timestamps": {"status": "STALE"}}, critical_checks_passed=True))

    def test_shared_feed_warning_only_with_explicit_evidence(self):
        bemobi = {
            "status": "partial", "report_feed_warning_non_blocking": True,
            "non_blocking_degraded": True,
            "ir_news": {"status": "ok", "report_feed_status": "empty"},
            "ir": {"status": "ok"}, "result_release": {"status": "skipped"},
            "distribution_ingestion": {"status": "ok"}, "distribution_cash": {"status": "ok"},
        }
        result = {"status": "SUCCESS", "source_results": {"bemobi_web": bemobi},
                  "source_health": {"BEMOBI_IR": "DEGRADED"}}
        lines, count = operational_lines(result)
        self.assertEqual(count, 1)
        self.assertIn("Utdelingsinnlesing: ok", "\n".join(lines))
        bemobi["distribution_ingestion"] = {"status": "error"}
        self.assertEqual(operational_lines(result)[1], 2)


if __name__ == "__main__":
    unittest.main()
