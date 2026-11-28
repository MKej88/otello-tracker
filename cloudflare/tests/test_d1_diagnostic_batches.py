from __future__ import annotations

import unittest
from urllib.error import HTTPError

from d1_diagnostic_batches import query_batches, query_diagnostics


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


    def test_secondary_failure_does_not_hide_required_results(self):
        queries = [{"sql": f"SELECT {i}"} for i in range(18)]
        seen = []
        def post(chunk):
            seen.extend(q["sql"] for q in chunk)
            if any(q["sql"] == "SELECT 16" for q in chunk):
                raise HTTPError("https://example.invalid", 400, "private text", {}, None)
            return {"success": True, "result": [
                {"success": True, "results": [q["sql"]]} for q in chunk]}
        result = query_diagnostics(queries, post, optional_indices=(15, 16))["result"]
        self.assertEqual(result[17]["results"], ["SELECT 17"])
        self.assertEqual(result[15]["results"], ["SELECT 15"])
        self.assertEqual(result[16], {"success": False, "diagnostic_unavailable": True, "results": []})
        self.assertLess(seen.index("SELECT 17"), seen.index("SELECT 16"))
        with self.assertRaises(RuntimeError):
            query_diagnostics(queries, post, optional_indices=(15,))


    def test_optional_fallback_preserves_reduced_evidence(self):
        queries = [{"sql": f"SELECT {i}"} for i in range(3)]
        def post(chunk):
            if any(q["sql"] == "SELECT 1" for q in chunk):
                raise HTTPError("https://example.invalid", 400, "private text", {}, None)
            return {"success": True, "result": [
                {"success": True, "results": [q["sql"]]} for q in chunk]}
        result = query_diagnostics(queries, post, optional_indices=(1,),
                                   optional_fallbacks={1: {"sql": "SELECT 10"}})["result"]
        self.assertEqual(result[1]["results"], ["SELECT 10"])
        self.assertTrue(result[1]["diagnostic_reduced"])
        self.assertEqual(result[2]["results"], ["SELECT 2"])
        failed = query_diagnostics(queries, post, optional_indices=(1,),
                                   optional_fallbacks={1: {"sql": "SELECT 1"}})["result"]
        self.assertTrue(failed[1]["diagnostic_unavailable"])
        with self.assertRaises(ValueError):
            query_diagnostics(queries, post, optional_indices=(1,),
                              optional_fallbacks={1: {"sql": "DELETE FROM x"}})
