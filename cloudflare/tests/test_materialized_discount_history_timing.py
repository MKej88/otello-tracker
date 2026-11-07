"""Regression tests: NAV history timing must not change values or cache semantics."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import materialized_discount_history as navhistory  # noqa: E402


SOURCE_DATE = "2026-11-06"
PAYLOAD = {"ready": True, "estimated": {"ready": True}, "points": [1, 2, 3]}


def _entry(
    *,
    date: str = SOURCE_DATE,
    version: str = navhistory.PERIOD_CACHE_VERSION,
) -> dict[str, str]:
    return {
        "value": json.dumps({
            "source_date": date,
            "calculation_version": version,
            "payload": PAYLOAD,
        }),
        "updated_at": "2026-11-06T22:00:00Z",
    }


class NavHistoryTimingTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_precomputed_period_is_returned_unchanged(self) -> None:
        repository = AsyncMock()
        repository.first.side_effect = [
            {"max_date": SOURCE_DATE},
            _entry(),
        ]
        diagnostics: dict = {}
        with patch.object(navhistory, "discount_history", new_callable=AsyncMock) as live:
            result = await navhistory.materialized_discount_history(
                repository, days=365, max_points=72, diagnostics=diagnostics
            )
        self.assertEqual(result, PAYLOAD)
        self.assertIsNot(result, PAYLOAD)
        live.assert_not_awaited()
        self.assertEqual(diagnostics["cache"], "hit")
        self.assertEqual(diagnostics["reason"], "none")
        self.assertGreaterEqual(diagnostics["lookup_ms"], 0)
        self.assertEqual(diagnostics["fallback_ms"], 0.0)
        self.assertNotIn("diagnostics", result)

    async def test_precomputed_misses_keep_live_fallback_and_fixed_reason(self) -> None:
        cases = [
            ("no_history", None, _entry()),
            ("missing_entry", {"max_date": SOURCE_DATE}, None),
            ("date_mismatch", {"max_date": SOURCE_DATE}, _entry(date="2026-11-05")),
            ("version_mismatch", {"max_date": SOURCE_DATE}, _entry(version="old")),
        ]
        for expected_reason, latest, entry in cases:
            with self.subTest(reason=expected_reason):
                repository = AsyncMock()
                repository.first.side_effect = [latest, entry]
                diagnostics: dict = {}
                with (
                    patch.object(
                        navhistory, "discount_history",
                        AsyncMock(return_value=PAYLOAD),
                    ) as live,
                    patch.object(
                        navhistory, "_enrich_life360_period",
                        AsyncMock(return_value=PAYLOAD),
                    ) as enrich,
                ):
                    result = await navhistory.materialized_discount_history(
                        repository, days=365, max_points=72,
                        diagnostics=diagnostics,
                    )
                self.assertEqual(result, PAYLOAD)
                live.assert_awaited_once()
                enrich.assert_awaited_once()
                self.assertEqual(diagnostics["cache"], "fallback")
                self.assertEqual(diagnostics["reason"], expected_reason)
                self.assertGreaterEqual(diagnostics["lookup_ms"], 0)
                self.assertGreaterEqual(diagnostics["fallback_ms"], 0)
                self.assertNotIn("diagnostics", result)

    async def test_non_preset_bypasses_lookup_and_preserves_live_values(self) -> None:
        repository = AsyncMock()
        diagnostics: dict = {}
        with (
            patch.object(
                navhistory, "discount_history",
                AsyncMock(return_value=PAYLOAD),
            ) as live,
            patch.object(
                navhistory, "_enrich_life360_period",
                AsyncMock(return_value=PAYLOAD),
            ),
        ):
            result = await navhistory.materialized_discount_history(
                repository, days=365, max_points=600, diagnostics=diagnostics
            )
        self.assertEqual(result, PAYLOAD)
        repository.first.assert_not_awaited()
        live.assert_awaited_once()
        self.assertEqual(diagnostics["cache"], "fallback")
        self.assertEqual(diagnostics["reason"], "non_preset")

    async def test_fallback_error_is_not_hidden_and_time_is_recorded(self) -> None:
        repository = AsyncMock()
        diagnostics: dict = {}
        with patch.object(
            navhistory, "discount_history",
            AsyncMock(side_effect=RuntimeError("live fallback failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "live fallback failed"):
                await navhistory.materialized_discount_history(
                    repository, days=365, max_points=600, diagnostics=diagnostics
                )
        self.assertGreaterEqual(diagnostics["fallback_ms"], 0)
        self.assertEqual(diagnostics["cache"], "fallback")


if __name__ == "__main__":
    unittest.main()
