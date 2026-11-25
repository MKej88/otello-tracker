import unittest

from status_email_report import operational_lines


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


if __name__ == "__main__":
    unittest.main()
