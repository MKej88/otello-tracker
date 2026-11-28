import unittest
from datetime import datetime, UTC
from nightly_diagnostic_fallback import fallback_needed


class FallbackTest(unittest.TestCase):
    def test_before_deadline_no_fallback(self):
        self.assertFalse(fallback_needed(datetime(2026,11,28,4,29,tzinfo=UTC),""))

    def test_stale_or_missing_report(self):
        now=datetime(2026,11,28,6,17,tzinfo=UTC)
        self.assertTrue(fallback_needed(now,"- Datadato: `2026-11-26`"))
        self.assertTrue(fallback_needed(now,""))

    def test_current_success_and_incomplete(self):
        now=datetime(2026,11,28,6,17,tzinfo=UTC)
        body="""- Datadato: `2026-11-27`
- Samlet status: **ADVARSEL**
| GitHub Actions – diagnose | success |
| D1-produksjonsdiagnose | ADVARSEL |
| Fulloppdatering (D1) | SUCCESS |
| Workflow-instans | complete |
"""
        self.assertFalse(fallback_needed(now,body))
        self.assertTrue(fallback_needed(now,body.replace("SUCCESS","FAILED")))
        self.assertTrue(fallback_needed(now,body.replace("ADVARSEL","AVVIK")))
        self.assertTrue(fallback_needed(now,body.replace("complete","running")))

    def test_unconfirmed_or_missing_d1_needs_fallback(self):
        now = datetime(2026, 11, 28, 6, 17, tzinfo=UTC)
        body = """- Datadato: `2026-11-27`
- Samlet status: **OK**
| GitHub Actions – diagnose | success |
| D1-produksjonsdiagnose | OK |
| Fulloppdatering (D1) | SUCCESS |
| Workflow-instans | complete |
"""
        self.assertFalse(fallback_needed(now, body))
        for report in (
            body.replace("**OK**", "**IKKE BEKREFTET**"),
            body.replace("| D1-produksjonsdiagnose | OK |", "| D1-produksjonsdiagnose | IKKE BEKREFTET |"),
            body.replace("| D1-produksjonsdiagnose | OK |", ""),
            body.replace("- Samlet status: **OK**", ""),
            body.replace("| D1-produksjonsdiagnose | OK |", "| D1-produksjonsdiagnose | AVVIK |"),
        ):
            with self.subTest(report=report):
                self.assertTrue(fallback_needed(now, report))
