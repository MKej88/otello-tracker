from __future__ import annotations

import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta

from src.exchangerate_dev_fx import (
    current_indicative_brl_nok,
    parse_brl_nok,
    refresh_exchangerate_dev_brl_nok,
)

NOW = datetime(2026, 10, 26, 17, 10, tzinfo=UTC)
OBSERVED = "2026-10-26T16:54:59Z"


def response_payload(**overrides):
    data = {
        "result": "success",
        "base": "BRL",
        "source": "live",
        "sources": {"NOK": "live"},
        "market_session": "open",
        "rates": {"NOK": 1.7113},
        "effective_at": {"NOK": OBSERVED},
        "stale": {"NOK": False},
        "derived_symbols": ["NOK"],
    }
    data.update(overrides)
    return data


class FakeResponse:
    ok = True
    status = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    async def text(self):
        return json.dumps(self.payload)


class FakeRepo:
    def __init__(self, *, nb="1.72", previous=None, live_row=None):
        self.nb = nb
        self.previous = previous
        self.live_row = live_row
        self.writes = []
        self.queries = []

    async def first(self, sql, args=()):
        self.queries.append((sql, args))
        if "s.code='EXCHANGERATE_DEV'" in sql:
            return self.live_row
        if "s.code='NORGES_BANK'" in sql:
            return {"rate": self.nb} if self.nb else None
        if "s.code=?" in sql:
            return self.previous
        return None

    async def source_id(self, code):
        self.source = code
        return 42

    async def run(self, sql, args=()):
        self.writes.append((sql, args))


class ExchangerateDevTests(unittest.TestCase):
    def test_live_quote_and_derived_metadata(self):
        quote = parse_brl_nok(response_payload(), now=NOW)
        self.assertEqual(str(quote["rate"]), "1.7113")
        self.assertTrue(quote["derived"])
        self.assertEqual(quote["observed_at"], OBSERVED)
        self.assertGreater(quote["age_minutes"], 15)

    def test_rejects_bad_or_stale_or_nonlive_quotes(self):
        variants = (
            {"stale": {"NOK": True}},
            {"market_session": "weekend"},
            {"source": "ecb_daily"},
            {"sources": {"NOK": "market_daily"}},
            {"rates": {"NOK": -1}},
            {"effective_at": {"NOK": "2026-10-25T17:00:00Z"}},
            {"effective_at": {"NOK": "2026-10-26T18:11:00Z"}},
            {"effective_at": {"NOK": "2026-10-26T15:00:00Z"}},
        )
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                parse_brl_nok(response_payload(**variant), now=NOW)

    def test_disabled_never_calls_network(self):
        async def fetch(*args, **kwargs):
            raise AssertionError("must not fetch")
        for enabled, approved, key in (
            (False, True, "secret"),
            (True, False, "secret"),
        ):
            result = asyncio.run(refresh_exchangerate_dev_brl_nok(
                FakeRepo(), now=NOW, enabled=enabled,
                license_approved=approved, api_key=key, fetcher=fetch,
            ))
            self.assertEqual(result["status"], "skipped")
            self.assertTrue(result["network_fetches_avoided"])

    def test_good_quote_persists_one_row_without_key_in_metadata(self):
        repo = FakeRepo()
        seen = []
        async def fetch(url, headers):
            seen.append((url, headers))
            return FakeResponse(response_payload())
        outcome = asyncio.run(refresh_exchangerate_dev_brl_nok(
            repo, now=NOW, enabled=True, license_approved=True,
            api_key="test-secret", fetcher=fetch,
        ))
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["rows_written"], 1)
        self.assertEqual(repo.source, "EXCHANGERATE_DEV")
        self.assertEqual(repo.writes[0][1], (OBSERVED, "1.7113", 42))
        self.assertEqual(seen[0][1]["Authorization"], "Bearer test-secret")
        self.assertNotIn("test-secret", str(outcome))
        self.assertNotIn("test-secret", str(repo.writes))

    def test_public_keyless_quote_persists_without_auth_header(self):
        repo = FakeRepo()
        requested = []
        async def fetch(url, headers):
            requested.append((url, headers))
            return FakeResponse(response_payload())
        outcome = asyncio.run(refresh_exchangerate_dev_brl_nok(
            repo, now=NOW, enabled=True, license_approved=True,
            api_key=None, fetcher=fetch,
        ))
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["rows_written"], 1)
        self.assertEqual(len(repo.writes), 1)
        self.assertNotIn("Authorization", requested[0][1])
        self.assertEqual(requested[0][1]["Accept"], "application/json")

    def test_outlier_or_network_failure_never_writes(self):
        for nb, payload in (("2.50", response_payload()), ("1.72", response_payload(rates={"NOK": 0.3}))):
            repo = FakeRepo(nb=nb)
            async def fetch(url, headers):
                return FakeResponse(payload)
            result = asyncio.run(refresh_exchangerate_dev_brl_nok(
                repo, now=NOW, enabled=True, license_approved=True,
                api_key="secret", fetcher=fetch,
            ))
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(repo.writes, [])

    def test_duplicate_observation_is_not_persisted(self):
        repo = FakeRepo(previous={"observed_at": OBSERVED, "rate": "1.71"})
        async def fetch(url, headers):
            return FakeResponse(response_payload())
        result = asyncio.run(refresh_exchangerate_dev_brl_nok(
            repo, now=NOW, enabled=True, license_approved=True,
            api_key="secret", fetcher=fetch,
        ))
        self.assertEqual(result["reason"], "observation_not_newer")
        self.assertEqual(repo.writes, [])

    def test_intraday_selection_only_today(self):
        repo = FakeRepo(live_row={"rate": "1.7113", "source_code": "EXCHANGERATE_DEV"})
        recent = asyncio.run(current_indicative_brl_nok(repo, day="2026-10-26", now=NOW))
        self.assertEqual(recent["source_code"], "EXCHANGERATE_DEV")
        self.assertEqual(len(repo.queries), 1)
        self.assertIsNone(asyncio.run(current_indicative_brl_nok(repo, day="2026-10-25", now=NOW)))
        self.assertEqual(len(repo.queries), 1)
        self.assertIn("75", str(timedelta(minutes=75).total_seconds() / 60))


if __name__ == "__main__":
    unittest.main()
