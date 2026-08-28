from __future__ import annotations

import sys
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from news_events import _company_name  # noqa: E402


class CompanyNameTest(unittest.TestCase):
    def test_returns_names_for_companies_shown_in_dashboard(self) -> None:
        self.assertEqual(_company_name("OTEC"), "Otello")
        self.assertEqual(_company_name("BMOB3"), "Bemobi")

    def test_rejects_companies_outside_dashboard(self) -> None:
        self.assertIsNone(_company_name("LIF"))
        self.assertIsNone(_company_name(None))


if __name__ == "__main__":
    unittest.main()
