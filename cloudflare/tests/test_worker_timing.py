"""Worker fetch timings are additive, bounded and independent of financial payloads."""
from __future__ import annotations

import unittest

from src.worker_timing import append_worker_timing, worker_timing_header


class JSHeaders:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, name):
        return self.data.get(name)

    def set(self, name, value):
        self.data[name] = value


class JSResponse:
    def __init__(self, headers=None):
        self.headers = JSHeaders(headers)
        self.status = 200
        self.body = b'{"ready":true}'


class WorkerTimingTests(unittest.TestCase):
    def test_timings_expose_only_bounded_fixed_labels(self):
        self.assertEqual(
            worker_timing_header(fetch_ms=202.345, asgi_import_ms=0.032,
                                 asgi_ms=179.945),
            "otello_fetch;dur=202.34, otello_asgi_import;dur=0.03, "
            "otello_asgi;dur=179.94",
        )
        self.assertEqual(
            worker_timing_header(fetch_ms=-3, asgi_import_ms=190000,
                                 asgi_ms=0),
            "otello_fetch;dur=0.00, otello_asgi_import;dur=120000.00, "
            "otello_asgi;dur=0.00",
        )

    def test_append_preserves_server_timing_json_status_and_cache(self):
        response = JSResponse({
            "Server-Timing": 'otello_snapshot;desc="hit", otello_handler;dur=122.00',
            "Cloudflare-CDN-Cache-Control": "public, max-age=300",
        })
        original_body = response.body
        result = append_worker_timing(
            response, fetch_ms=240.1, asgi_import_ms=1.2, asgi_ms=231.0
        )
        self.assertIs(result, response)
        self.assertEqual(result.body, original_body)
        self.assertEqual(result.status, 200)
        self.assertEqual(
            result.headers.get("Server-Timing"),
            'otello_snapshot;desc="hit", otello_handler;dur=122.00, '
            "otello_fetch;dur=240.10, otello_asgi_import;dur=1.20, "
            "otello_asgi;dur=231.00",
        )
        self.assertEqual(
            result.headers.get("Cloudflare-CDN-Cache-Control"),
            "public, max-age=300",
        )

    def test_missing_existing_metric_is_not_an_error(self):
        response = JSResponse()
        append_worker_timing(
            response, fetch_ms=9.0, asgi_import_ms=0.0, asgi_ms=8.0
        )
        self.assertTrue(response.headers.get("Server-Timing").startswith(
            "otello_fetch;dur=9.00"
        ))


if __name__ == "__main__":
    unittest.main()
