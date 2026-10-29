"""Timing diagnostics must not change API payloads or mask D1 errors."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Response

from src import app as api


class _MetricsRepository:
    def performance_metrics(self):
        return {
            "d1_read_ms": 123.45,
            "d1_reads": 14,
        }


class OriginServerTimingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repository = _MetricsRepository()
        self.request = SimpleNamespace(scope={})
        self.response = Response()

    def assert_origin_timing(self):
        self.assertRegex(
            self.response.headers["server-timing"],
            r'^otello_handler;dur=\d+\.\d{2}, '
            r'otello_d1;dur=123\.45, otello_reads;desc="14"$',
        )

    async def test_bemobi_dashboard_payload_and_origin_header(self):
        expected = {"ready": True, "market": {"price_brl": 10}}
        with patch.object(api, "_repository", return_value=self.repository), patch(
            "bemobi_dashboard.bemobi_dashboard", new_callable=AsyncMock
        ) as dashboard:
            dashboard.return_value = expected
            actual = await api.get_bemobi_dashboard(self.request, self.response)
        self.assertEqual(actual, expected)
        self.assert_origin_timing()

    async def test_bemobi_consensus_payload_and_origin_header(self):
        expected = {"ready": True, "coverage": {}}
        with patch.object(api, "_repository", return_value=self.repository), patch(
            "bemobi_consensus_investor.bemobi_consensus", new_callable=AsyncMock
        ) as consensus:
            consensus.return_value = expected
            actual = await api.get_bemobi_consensus(self.request, self.response)
        self.assertEqual(actual, expected)
        self.assert_origin_timing()

    async def test_buyback_dashboard_payload_and_origin_header(self):
        expected = {"status": "ok"}
        with patch.object(api, "_repository", return_value=self.repository), patch(
            "buyback_dashboard.buyback_dashboard", new_callable=AsyncMock
        ) as dashboard:
            dashboard.return_value = expected
            actual = await api.get_buyback_dashboard(self.request, self.response, None)
        self.assertEqual(actual, expected)
        self.assert_origin_timing()

    async def test_backend_exception_is_not_masked(self):
        with patch.object(api, "_repository", return_value=self.repository), patch(
            "bemobi_dashboard.bemobi_dashboard", new_callable=AsyncMock
        ) as dashboard:
            dashboard.side_effect = RuntimeError("D1 connection failed")
            with self.assertRaisesRegex(RuntimeError, "D1 connection failed"):
                await api.get_bemobi_dashboard(self.request, self.response)
        self.assertNotIn("server-timing", self.response.headers)


if __name__ == "__main__":
    unittest.main()
