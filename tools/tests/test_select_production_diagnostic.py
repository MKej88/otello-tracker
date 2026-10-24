import unittest
from datetime import UTC, datetime, timedelta
from select_production_diagnostic import select_production_diagnostic


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 24, 5, 5, tzinfo=UTC)

    def record(self, event, age, branch="main"):
        return {"id": age, "event": event, "head_branch": branch,
                "status": "completed",
                "created_at": (self.now - timedelta(minutes=age)).isoformat()}

    def test_ignores_newer_push(self):
        self.assertEqual(select_production_diagnostic(
            [self.record("push", 1), self.record("schedule", 32)],
            scheduled=True, now=self.now)["id"], 32)

    def test_scheduled_ignores_manual(self):
        self.assertEqual(select_production_diagnostic(
            [self.record("workflow_dispatch", 2), self.record("schedule", 30)],
            scheduled=True, now=self.now)["id"], 30)

    def test_manual_can_select_manual(self):
        self.assertEqual(select_production_diagnostic(
            [self.record("workflow_dispatch", 4)], scheduled=False,
            now=self.now)["id"], 4)

    def test_stale_schedule_rejected(self):
        with self.assertRaises(ValueError):
            select_production_diagnostic([self.record("schedule", 181)],
                                         scheduled=True, now=self.now)

    def test_nonproduction_never_counts(self):
        with self.assertRaises(ValueError):
            select_production_diagnostic([self.record("push", 1),
                                          self.record("schedule", 5, "feature")],
                                         scheduled=False, now=self.now)


if __name__ == "__main__":
    unittest.main()
