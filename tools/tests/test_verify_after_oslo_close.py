from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloudflare" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from verify_after_oslo_close import evaluate, should_verify  # noqa: E402


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class LiveProbeTests(unittest.TestCase):
    def test_dst_half_day_weekend_and_regular_close(self):
        for iso in ("2026-11-18T16:15:00Z", "2026-07-08T15:15:00Z",
                    "2026-04-01T11:55:00Z"):
            self.assertTrue(should_verify(dt(iso)), iso)
        for iso in ("2026-11-18T15:15:00Z", "2026-07-08T16:15:00Z",
                    "2026-11-21T16:15:00Z", "2026-12-25T16:15:00Z"):
            self.assertFalse(should_verify(dt(iso)), iso)

    def test_validates_all_three_cards_without_fabricating_reference(self):
        healthy = {
            "ready": True, "status": "ready",
            "fx_movement": {"ready": True},
            "otec_effect": {"ready": True},
        }
        self.assertEqual(evaluate(healthy), [])
        bad = {
            "ready": False, "status": "missing_reference",
            "fx_movement": {"ready": False, "reason": "missing_oslo_close_fx_reference"},
        }
        self.assertEqual(evaluate(bad), [
            "bemobi:missing_reference",
            "brlnok:missing_oslo_close_fx_reference",
            "otec:missing_effect",
        ])
        self.assertEqual(evaluate({**healthy, "fx_movement": {"ready": False}}, require_fx=False), [])


if __name__ == "__main__":
    unittest.main()
