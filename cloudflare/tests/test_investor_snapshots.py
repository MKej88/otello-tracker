"""Scheduled investor snapshots preserve live API shape, dates and failure fallbacks."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Response
from src import app as api
from src import investor_snapshots as snapshots


CLOCK = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class MemoryRepository:
    def __init__(self):
        self.rows = {}
        self.reads = 0
        self.writes = 0

    async def first(self, sql, parameters=()):
        assert "runtime_state" in sql
        self.reads += 1
        row = self.rows.get(parameters[0])
        return dict(row) if row else None

    async def run(self, sql, parameters=()):
        assert "runtime_state" in sql
        key, value, updated_at = parameters
        self.rows[key] = {"value": value, "updated_at": updated_at}
        self.writes += 1

    def performance_metrics(self):
        return {"d1_read_ms": 0, "d1_reads": self.reads}


async def fake_consensus(_repo, *, bemobi_payload=None):
    assert bemobi_payload == {"ready": True, "market": {"price_brl": 12.5}}
    return {"ready": True, "coverage": {"analysts": 2}}


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = MemoryRepository()

    async def _seed(self):
        with (
            patch("bemobi_dashboard.bemobi_dashboard", new=AsyncMock(
                return_value={"ready": True, "market": {"price_brl": 12.5}}
            )) as bemobi,
            patch("bemobi_consensus_investor.bemobi_consensus", side_effect=fake_consensus) as consensus,
            patch("buyback_dashboard.buyback_dashboard", new=AsyncMock(
                return_value={"ready": True, "status": "OK", "as_of_date": "2026-10-29"}
            )) as buybacks,
        ):
            result = await snapshots.refresh_investor_snapshots(self.repo, now=CLOCK)
        self.assertEqual(bemobi.await_count, 1)
        self.assertEqual(consensus.await_count, 1)
        buybacks.assert_awaited_once_with(self.repo, as_of_date="2026-10-29")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.repo.writes, 3)
        return result

    async def test_writes_three_independent_json_snapshots_and_reuses_bemobi(self):
        await self._seed()
        self.assertEqual(
            await snapshots.load_investor_snapshot(
                self.repo, "bemobi_dashboard", now=CLOCK + timedelta(minutes=2)
            ),
            {"ready": True, "market": {"price_brl": 12.5}},
        )
        self.assertEqual(
            await snapshots.load_investor_snapshot(
                self.repo, "bemobi_consensus", now=CLOCK
            ),
            {"ready": True, "coverage": {"analysts": 2}},
        )
        buyback_payload = await snapshots.load_investor_snapshot(
            self.repo, "buybacks_dashboard", now=CLOCK
        )
        self.assertEqual(buyback_payload["as_of_date"], "2026-10-29")

    async def test_expired_future_and_version_mismatched_snapshots_fall_back(self):
        await self._seed()
        self.assertIsNone(await snapshots.load_investor_snapshot(
            self.repo, "buybacks_dashboard", now=CLOCK + timedelta(minutes=41)
        ))
        self.assertIsNone(await snapshots.load_investor_snapshot(
            self.repo, "buybacks_dashboard", now=CLOCK - timedelta(minutes=1)
        ))
        key = snapshots.KEYS["buybacks_dashboard"]
        self.repo.rows[key]["value"] = '{"version":999,"payload":{"ready":true}}'
        self.assertIsNone(await snapshots.load_investor_snapshot(
            self.repo, "buybacks_dashboard", now=CLOCK
        ))

    async def test_oslo_midnight_invalidates_snapshot_even_under_forty_minutes(self):
        on_oct_29 = datetime(2026, 10, 29, 22, 45, tzinfo=UTC)
        with (
            patch("bemobi_dashboard.bemobi_dashboard", new=AsyncMock(return_value={"ready": True})),
            patch("bemobi_consensus_investor.bemobi_consensus", new=AsyncMock(return_value={"ready": True})),
            patch("buyback_dashboard.buyback_dashboard", new=AsyncMock(return_value={"ready": True})),
        ):
            await snapshots.refresh_investor_snapshots(self.repo, now=on_oct_29)
        self.assertIsNone(await snapshots.load_investor_snapshot(
            self.repo, "buybacks_dashboard",
            now=on_oct_29 + timedelta(minutes=30),
        ))

    async def test_snapshot_hit_skips_expensive_calculations(self):
        await self._seed()
        request = SimpleNamespace(scope={})
        with (
            patch.object(api, "_repository", return_value=self.repo),
            patch("investor_snapshots._clock", return_value=CLOCK),
            patch("bemobi_dashboard.bemobi_dashboard", side_effect=AssertionError("Unexpected live Bemobi")),
            patch("bemobi_consensus_investor.bemobi_consensus", side_effect=AssertionError("Unexpected live consensus")),
            patch("buyback_dashboard.buyback_dashboard", side_effect=AssertionError("Unexpected live buyback")),
        ):
            response_bemobi = Response()
            bemobi = await api.get_bemobi_dashboard(request, response_bemobi)
            response_consensus = Response()
            consensus = await api.get_bemobi_consensus(request, response_consensus)
            response_buyback = Response()
            buyback = await api.get_buyback_dashboard(request, response_buyback, None)
        self.assertEqual(bemobi["market"]["price_brl"], 12.5)
        self.assertEqual(consensus["coverage"]["analysts"], 2)
        self.assertEqual(buyback["status"], "OK")
        self.assertIn('otello_snapshot;desc="hit"', response_bemobi.headers["server-timing"])
        self.assertIn('otello_snapshot;desc="hit"', response_consensus.headers["server-timing"])
        self.assertIn('otello_snapshot;desc="hit"', response_buyback.headers["server-timing"])

    async def test_historical_buyback_date_does_not_read_cached_today(self):
        await self._seed()
        request = SimpleNamespace(scope={})
        with (
            patch.object(api, "_repository", return_value=self.repo),
            patch("buyback_dashboard.buyback_dashboard", new=AsyncMock(
                return_value={"ready": True, "as_of_date": "2026-09-30"}
            )) as calculate,
        ):
            result = await api.get_buyback_dashboard(request, Response(), "2026-09-30")
        self.assertEqual(result["as_of_date"], "2026-09-30")
        calculate.assert_awaited_once_with(self.repo, as_of_date="2026-09-30")

    async def test_failed_rebuild_preserves_previous_snapshot(self):
        await self._seed()
        key = snapshots.KEYS["bemobi_dashboard"]
        before = self.repo.rows[key]["value"]
        with (
            patch("bemobi_dashboard.bemobi_dashboard", side_effect=RuntimeError("D1 unavailable")),
            patch("bemobi_consensus_investor.bemobi_consensus", new=AsyncMock(
                return_value={"ready": False}
            )),
            patch("buyback_dashboard.buyback_dashboard", new=AsyncMock(
                return_value={"ready": False}
            )),
        ):
            result = await snapshots.refresh_investor_snapshots(self.repo, now=CLOCK + timedelta(minutes=1))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["components"]["bemobi_dashboard"]["error_type"], "RuntimeError")
        self.assertEqual(self.repo.rows[key]["value"], before)


if __name__ == "__main__":
    unittest.main()
