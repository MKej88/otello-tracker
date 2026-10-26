from __future__ import annotations

import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from src.after_oslo_fx import (
    REFERENCE_PREFIX,
    capture_fx_close_reference,
    fx_close_movement,
)
from src.bemobi_after_oslo import closing_auction, otec_effect, iso

CLOSE = closing_auction(datetime(2026, 10, 26, tzinfo=UTC).date()).astimezone(UTC)
# 16:25 Oslo during standard time: 15:25 UTC.
OBSERVED = iso(CLOSE - timedelta(seconds=1))
NOW = CLOSE + timedelta(minutes=16)


class Response:
    ok = True
    status = 200
    headers = {}

    def __init__(self, rate=1.71, observed=OBSERVED):
        self.data = {
            "result": "success", "base": "BRL", "source": "live",
            "sources": {"NOK": "live"}, "market_session": "open",
            "rates": {"NOK": rate}, "effective_at": {"NOK": observed},
            "stale": {"NOK": False}, "derived_symbols": ["NOK"],
        }

    async def text(self):
        return json.dumps(self.data)


class Repository:
    def __init__(self, *, frozen=None, latest=None):
        self.frozen = frozen
        self.latest = latest
        self.writes = []
        self.query_count = 0

    async def first(self, sql, args=()):
        self.query_count += 1
        if "runtime_state" in sql:
            return {"value": json.dumps(self.frozen)} if self.frozen else None
        if "s.code='EXCHANGERATE_DEV'" in sql:
            return self.latest
        if "s.code='NORGES_BANK'" in sql:
            return {"rate": "1.72", "observed_at": iso(CLOSE - timedelta(days=1)), "source": "NORGES_BANK"}
        if "market_prices" in sql:
            return {"price": "18.50", "price_type": "CLOSE", "observed_at": iso(CLOSE), "source": "EURONEXT"}
        if "bemobi_holdings" in sql:
            return {"shares": "100"}
        if "otello_share_counts" in sql:
            return {"outstanding_shares": "10"}
        return None

    async def source_id(self, code):
        if code != "EXCHANGERATE_DEV":
            raise AssertionError(code)
        return 21

    async def run(self, sql, args=()):
        self.writes.append((sql, args))
        if "INSERT INTO runtime_state" in sql:
            self.frozen = json.loads(args[1])


class OsloCloseFxTests(unittest.TestCase):
    def test_exact_near_close_observation_captured_and_frozen_once(self):
        repo = Repository()
        calls = []
        async def fetch(url, headers):
            calls.append((url, headers))
            return Response()
        result = asyncio.run(capture_fx_close_reference(
            repo, now=NOW, enabled=True, license_approved=True,
            api_key=None, fetcher=fetch,
        ))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(repo.frozen["observed_at"], OBSERVED)
        self.assertEqual(repo.frozen["oslo_close_at"], iso(CLOSE))
        self.assertEqual(len(repo.writes), 2)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Authorization", calls[0][1])
        again = asyncio.run(capture_fx_close_reference(
            repo, now=NOW + timedelta(minutes=1), enabled=True,
            license_approved=True, api_key="private", fetcher=fetch,
        ))
        self.assertEqual(again["reason"], "already_captured")
        self.assertEqual(len(calls), 1)

    def test_rejects_observation_far_from_close_without_fabricated_reference(self):
        for offset in (-4, 1):
            with self.subTest(offset=offset):
                repo = Repository()
                async def fetch(url, headers):
                    return Response(observed=iso(CLOSE + timedelta(minutes=offset)))
                result = asyncio.run(capture_fx_close_reference(
                    repo, now=NOW, enabled=True, license_approved=True,
                    api_key=None, fetcher=fetch,
                ))
                self.assertEqual(result["reason"], "observation_not_near_oslo_close")
                self.assertEqual(repo.writes, [])

    def test_license_flag_blocks_network(self):
        repo = Repository()
        async def fetch(*args, **kwargs):
            raise AssertionError("must not fetch")
        result = asyncio.run(capture_fx_close_reference(
            repo, now=NOW, enabled=True, license_approved=False, api_key=None,
            fetcher=fetch,
        ))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(repo.writes, [])

    def test_uses_only_later_exr_observation_from_same_close_basis(self):
        frozen = {"rate": "1.70", "source": "EXCHANGERATE_DEV", "observed_at": OBSERVED,
                  "oslo_close_at": iso(CLOSE)}
        repo = Repository(frozen=frozen, latest={"rate": "1.75", "observed_at": iso(CLOSE + timedelta(hours=2))})
        value = asyncio.run(fx_close_movement(repo, CLOSE, CLOSE + timedelta(hours=3)))
        self.assertTrue(value["ready"])
        self.assertAlmostEqual(value["change_pct"], (1.75/1.70-1)*100, places=8)
        self.assertEqual(value["reference_at"], OBSERVED)
        self.assertEqual(value["latest_source"], "EXCHANGERATE_DEV")

    def test_missing_or_misaligned_reference_returns_missing_not_daily_proxy(self):
        for frozen in (None, {"rate": "1.7", "source": "NORGES_BANK", "observed_at": OBSERVED, "oslo_close_at": iso(CLOSE)}):
            repo = Repository(frozen=frozen, latest={"rate": "1.75", "observed_at": iso(CLOSE + timedelta(hours=2))})
            move = asyncio.run(fx_close_movement(repo, CLOSE, CLOSE + timedelta(hours=3)))
            self.assertFalse(move["ready"])

    def test_effect_is_additive_without_double_counting_fx_interaction(self):
        frozen = {"rate": "1.70", "source": "EXCHANGERATE_DEV", "observed_at": OBSERVED,
                  "oslo_close_at": iso(CLOSE)}
        repo = Repository(frozen=frozen, latest={"rate": "1.75", "observed_at": iso(CLOSE + timedelta(hours=2))})
        # 10 Bemobi shares per OTEC; Bemobi 25 at close -> 24 now.
        effect = asyncio.run(otec_effect(
            repo, CLOSE, -1.0,
            latest_bemobi_price=24.0, current=CLOSE+timedelta(hours=3),
        ))
        self.assertTrue(effect["ready"])
        self.assertTrue(effect["fx_movement"]["ready"])
        self.assertAlmostEqual(effect["change_per_share_nok"], -17.0)
        self.assertAlmostEqual(effect["fx_movement"]["effect_per_share_nok"], 12.0)
        self.assertAlmostEqual(effect["fx_movement"]["combined_per_share_nok"], -5.0)
        self.assertAlmostEqual(effect["fx_movement"]["combined_per_share_nok"],
                               float((Decimal("24")*Decimal("1.75") - Decimal("25")*Decimal("1.70"))*10))

    def test_missing_reference_preserves_bemobi_only_value_but_not_combined(self):
        repo = Repository()
        effect = asyncio.run(otec_effect(
            repo, CLOSE, -1.0, latest_bemobi_price=24.0,
            current=CLOSE+timedelta(hours=3),
        ))
        self.assertTrue(effect["ready"])
        self.assertFalse(effect["fx_movement"]["ready"])
        self.assertNotIn("combined_per_share_nok", effect["fx_movement"])


if __name__ == "__main__":
    unittest.main()
