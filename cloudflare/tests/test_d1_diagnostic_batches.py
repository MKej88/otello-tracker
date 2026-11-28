from __future__ import annotations

import unittest
from urllib.error import HTTPError

from d1_diagnostic_batches import query_batches


class DiagnosticBatchTests(unittest.TestCase):
    def test_preserves_order_and_limits_batch(self):
        queries = [{"sql": f"SELECT {i}"} for i in range(18)]
        seen = []
        def post(chunk):
            seen.append(len(chunk))
            return {"success": True, "result": [
                {"success": True, "results": [q["sql"]]} for q in chunk]}
        result = query_batches(queries, post)
        self.assertEqual(seen, [6, 6, 6])
        self.assertEqual([r["results"][0] for r in result["result"]],
                         [q["sql"] for q in queries])

    def test_splits_http_400_and_names_bad_query(self):
        queries = [{"sql": f"SELECT {i}"} for i in range(6)]
        def post(chunk):
            if len(chunk) > 1:
                raise HTTPError("https://example.invalid", 400, "private text", {}, None)
            return {"success": True, "result": [{"success": True, "results": []}]}
        self.assertEqual(len(query_batches(queries, post)["result"]), 6)
        def broken(chunk):
            if any(q["sql"] == "SELECT 3" for q in chunk):
                raise HTTPError("https://example.invalid", 400, "private text", {}, None)
            return post(chunk)
        with self.assertRaisesRegex(RuntimeError, "spørring 4–4 feilet \\(HTTP 400\\)"):
            query_batches(queries, broken)

    def test_never_accepts_missing_or_failed_result(self):
        with self.assertRaises(RuntimeError):
            query_batches([{"sql": "SELECT 1"}], lambda _: {"success": True, "result": []})
        with self.assertRaises(ValueError):
            query_batches([{"sql": "DELETE FROM x"}], lambda _: {})
