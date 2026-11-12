"""Request-scoped API D1 timings must preserve payload, cache and privacy."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.responses import JSONResponse
from starlette.requests import Request

from src import app as api


def _request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "server": ("example.test", 443),
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "env": SimpleNamespace(DB=object()),
    })


class RequestD1TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_endpoints_expose_only_aggregate_counts_and_durations(self):
        for path in sorted(api.D1_TIMING_ROUTES):
            with self.subTest(path=path):
                request = _request(path)

                async def call_next(req):
                    repository = api._repository(req)
                    repository._read_ms = 145.25
                    repository._read_queries = 8
                    return JSONResponse({"ready": True})

                response = await api.add_response_hardening(request, call_next)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.body, b'{"ready":true}')
                self.assertIn("otello_req_d1;dur=145.25", response.headers["server-timing"])
                self.assertIn('otello_req_reads;desc="8"', response.headers["server-timing"])
                self.assertIn("otello_fastapi;dur=", response.headers["server-timing"])
                self.assertEqual(
                    response.headers["cloudflare-cdn-cache-control"],
                    api.CACHE_POLICIES[path][1],
                )
                self.assertNotIn("SELECT", response.headers["server-timing"])
                self.assertNotIn("customer", response.headers["server-timing"])

    async def test_other_apis_keep_their_existing_timing_without_d1_metadata(self):
        request = _request("/api/dashboard/summary")

        async def call_next(req):
            api._repository(req)
            return JSONResponse({"ready": True}, headers={"Server-Timing": "existing;dur=10"})

        response = await api.add_response_hardening(request, call_next)
        self.assertIn("existing;dur=10", response.headers["server-timing"])
        self.assertIn("otello_fastapi;dur=", response.headers["server-timing"])
        self.assertNotIn("otello_req_d1", response.headers["server-timing"])

    async def test_missing_repository_does_not_break_diagnostic_response(self):
        request = _request("/api/news-events")

        async def call_next(_):
            return JSONResponse({"ready": False}, status_code=503)

        response = await api.add_response_hardening(request, call_next)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("otello_req_reads", response.headers["server-timing"])


if __name__ == "__main__":
    unittest.main()
