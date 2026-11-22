"""FX dashboard: independent D1 reads overlap without changing financial output."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.fx_dashboard import fx_dashboard


class Repository:
    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def first(self, sql, parameters=()):
        assert "MAX(substr(fr.observed_at, 1, 10))" in sql
        return {"max_date": "2026-10-26"}

    async def all(self, sql, parameters=()):
        assert "substr(fr.observed_at, 1, 10) BETWEEN ? AND ?" in sql
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.002)
            return [
                {"rate_date": "2026-10-23", "rate": "1.8" if parameters[0] == "BRL" else "9.3",
                 "source_code": "NORGES_BANK"},
                {"rate_date": "2026-10-26", "rate": "1.7" if parameters[0] == "BRL" else "9.4",
                 "source_code": "NORGES_BANK"},
            ]
        finally:
            self.active -= 1


class FXDashboardPerformanceTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_queries_and_diagnostics_preserve_values(self):
        repo = Repository()
        diagnostics = {}
        with patch("src.fx_dashboard.latest_indicative_brl_nok",
                   new=AsyncMock(return_value=None)):
            payload = await fx_dashboard(repo, diagnostics=diagnostics)
        self.assertGreaterEqual(repo.max_active, 2)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["as_of_date"], "2026-10-26")
        self.assertEqual(payload["current"]["source"], "NORGES_BANK")
        self.assertEqual(payload["current"]["brl_nok"], 1.7)
        self.assertEqual(payload["current"]["usd_nok"], 9.4)
        self.assertEqual(payload["series"][-1]["brl_nok"], 1.7)
        for name in ("lookup_ms", "brl_ms", "usd_ms", "spot_ms", "compute_ms"):
            self.assertIn(name, diagnostics)
            self.assertGreaterEqual(diagnostics[name], 0)
        self.assertNotIn("diagnostics", payload)


if __name__ == "__main__":
    unittest.main()
