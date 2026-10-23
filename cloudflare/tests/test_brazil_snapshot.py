from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import brazil_snapshot as snapshot  # noqa: E402


class BrazilSnapshotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.payload = {
            "ready": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "as_of_date": "2026-10-09",
            "metrics": {key: {"value": 15} for key in (
                "selic", "ipca_12m", "ibc_br", "ibc_services", "brl_nok"
            )},
            "focus": {"values": {
                key: {str(year): {"median": 12} for year in (2026, 2027)}
                for key in ("selic", "ipca", "gdp", "usd_brl")
            }},
            "focus_trend": {"comparisons": {"30d": {"points_by_year": {
                str(year): {key: {"change": 0} for key in ("selic", "ipca", "gdp")}
                for year in (2026, 2027)
            }}}},
        }
        self.repository = AsyncMock()
        self.repository.first.return_value = {"value": json.dumps(self.payload)}

    async def test_first_visitor_uses_snapshot_without_external_requests(self) -> None:
        with patch.object(snapshot, "build_dashboard", AsyncMock()) as build:
            result = await snapshot.cached_brazil_dashboard(self.repository)
        self.assertEqual(result, self.payload)
        build.assert_not_awaited()
        self.repository.first.assert_awaited_once()
        self.repository.run.assert_not_awaited()

    async def test_cache_miss_is_fast_and_never_fetches_external_sources(self) -> None:
        self.repository.first.return_value = None
        with patch.object(snapshot, "build_dashboard", AsyncMock()) as build:
            result = await snapshot.cached_brazil_dashboard(self.repository)
        self.assertEqual(result, {
            "ready": False, "snapshot_unavailable": True, "source_status": {},
        })
        build.assert_not_awaited()
        self.repository.run.assert_not_awaited()

    async def test_expired_but_recent_snapshot_is_returned_without_live_fetch(self) -> None:
        self.payload["generated_at"] = (
            datetime.now(UTC) - timedelta(hours=2)
        ).isoformat()
        self.repository.first.return_value = {"value": json.dumps(self.payload)}
        with patch.object(snapshot, "build_dashboard", AsyncMock()) as build:
            result = await snapshot.cached_brazil_dashboard(self.repository)
        self.assertTrue(result["snapshot_stale"])
        self.assertEqual(result["generated_at"], self.payload["generated_at"])
        self.assertTrue(snapshot.snapshot_degraded(result))
        build.assert_not_awaited()

    async def test_older_than_seven_days_is_not_misrepresented_as_current(self) -> None:
        self.payload["generated_at"] = (
            datetime.now(UTC) - timedelta(seconds=snapshot.MAX_STALE_AGE_SECONDS + 1)
        ).isoformat()
        self.repository.first.return_value = {"value": json.dumps(self.payload)}
        with patch.object(snapshot, "build_dashboard", AsyncMock()) as build:
            result = await snapshot.cached_brazil_dashboard(self.repository)
        self.assertTrue(result["snapshot_unavailable"])
        build.assert_not_awaited()

    async def test_historical_request_bypasses_cache_and_does_not_replace_it(self) -> None:
        with patch.object(snapshot, "build_dashboard", AsyncMock(return_value=self.payload)) as build:
            await snapshot.cached_brazil_dashboard(self.repository, as_of_date="2026-08-01")
        build.assert_awaited_once_with(self.repository, as_of_date="2026-08-01")
        self.repository.first.assert_not_awaited()
        self.repository.run.assert_not_awaited()

    async def test_expired_future_and_malformed_snapshots_are_rejected(self) -> None:
        now = datetime.now(UTC)
        for value in ("bad json", "[]", json.dumps({"ready": True}), *(
            json.dumps({**self.payload, "generated_at": stamp}) for stamp in (
                (now - timedelta(seconds=snapshot.MAX_AGE_SECONDS + 1)).isoformat(),
                (now + timedelta(minutes=1)).isoformat(),
                "2026-09-30T12:00:00",
                None,
            )
        )):
            with self.subTest(value=value):
                self.repository.first.return_value = {"value": value}
                self.assertIsNone(await snapshot.load_snapshot(self.repository, now=now))

    async def test_failed_refresh_preserves_existing_snapshot(self) -> None:
        for outcome in (AsyncMock(return_value={"ready": False}), AsyncMock(side_effect=TimeoutError)):
            with patch.object(snapshot, "build_dashboard", outcome):
                try:
                    result = await snapshot.refresh_brazil_snapshot(self.repository)
                    self.assertEqual(result["status"], "error")
                except TimeoutError:
                    pass
            self.repository.run.assert_not_awaited()

    async def test_sgs_diagnostics_persists_only_whitelisted_metadata(self) -> None:
        diagnostics = {
            "ready": True, "live_ready": False, "fallback": True,
            "error": "PRIVATE_RAW_RESPONSE_MUST_NOT_BE_SAVED",
            "error_kind": "invalid_json", "http_status": 200,
            "content_type": "text/html", "response_bytes": 118,
            "response_kind": "html", "last_success_at": "2026-10-18T08:00:00Z",
            "response_excerpt": "PRIVATE_RAW_BODY",
        }
        payload = dict(self.payload, source_status={
            key: diagnostics for key in snapshot.SGS_KEYS
        })
        await snapshot.save_sgs_diagnostics(self.repository, payload)
        args = self.repository.run.await_args.args[1]
        self.assertEqual(args[0], snapshot.SGS_DIAGNOSTICS_STATE_KEY)
        stored = json.loads(args[1])
        self.assertEqual(stored["generated_at"], payload["generated_at"])
        self.assertEqual(len(stored["sources"]), 4)
        source = stored["sources"]["selic"]
        self.assertEqual(source["http_status"], 200)
        self.assertEqual(source["content_type"], "text/html")
        self.assertEqual(source["response_bytes"], 118)
        self.assertEqual(source["response_kind"], "html")
        self.assertFalse(source["live_ready"])
        self.assertEqual(source["last_success_at"], "2026-10-18T08:00:00Z")
        self.assertNotIn("error", source)
        self.assertNotIn("response_excerpt", source)
        self.assertNotIn("PRIVATE_", args[1])

    async def test_cron_persists_sgs_diagnostics_when_dashboard_is_not_ready(self) -> None:
        payload = {
            "ready": False,
            "generated_at": datetime.now(UTC).isoformat(),
            "as_of_date": "2026-10-19",
            "source_status": {
                "selic": {
                    "ready": False, "error_kind": "upstream_http_error",
                    "http_status": 403, "content_type": "text/html",
                    "response_bytes": 0, "response_kind": "empty",
                },
            },
        }
        with patch.object(snapshot, "build_dashboard", AsyncMock(return_value=payload)):
            result = await snapshot.refresh_brazil_snapshot(self.repository)
        self.assertEqual(result["status"], "error")
        self.repository.run.assert_awaited_once()
        self.assertEqual(self.repository.run.await_args.args[1][0],
                         snapshot.SGS_DIAGNOSTICS_STATE_KEY)

    async def test_cron_refresh_updates_snapshot(self) -> None:
        with patch.object(snapshot, "build_dashboard", AsyncMock(return_value=self.payload)):
            result = await snapshot.refresh_brazil_snapshot(self.repository)
        self.assertEqual(result["status"], "ok")
        self.repository.run.assert_awaited_once()

    async def test_cache_read_failure_does_not_trigger_live_source_fetch(self) -> None:
        self.repository.first.side_effect = RuntimeError("database unavailable")
        with patch.object(snapshot, "build_dashboard", AsyncMock()) as build:
            result = await snapshot.cached_brazil_dashboard(self.repository)
        self.assertTrue(result["snapshot_unavailable"])
        build.assert_not_awaited()

    async def test_partial_ready_response_does_not_replace_complete_snapshot(self) -> None:
        partial = dict(self.payload, metrics={"brl_nok": {"value": 1.9}})
        await snapshot.save_snapshot(self.repository, partial)
        self.repository.run.assert_not_awaited()

    async def test_newer_partial_can_replace_a_complete_snapshot_older_than_a_day(self) -> None:
        previous = dict(self.payload, generated_at=(
            datetime.now(UTC) - timedelta(hours=26)
        ).isoformat())
        self.repository.first.return_value = {"value": json.dumps(previous)}
        current = dict(self.payload, generated_at=datetime.now(UTC).isoformat(),
                       metrics={"brl_nok": {"value": 1.9}})
        await snapshot.save_snapshot(self.repository, current)
        self.repository.run.assert_awaited_once()
        query = self.repository.run.await_args.args[0]
        self.assertIn("julianday(excluded.updated_at) - julianday(runtime_state.updated_at) >= 1", query)

    async def test_partial_and_fallback_snapshots_expire_sooner(self) -> None:
        now = datetime.now(UTC)
        cases = (
            dict(self.payload, metrics={"brl_nok": {"value": 1.9}}),
            dict(self.payload, source_status={"selic": {"fallback": True}}),
            dict(self.payload, focus_trend={"comparisons": {}}),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                payload["generated_at"] = (now - timedelta(seconds=snapshot.PARTIAL_MAX_AGE_SECONDS + 1)).isoformat()
                self.repository.first.return_value = {"value": json.dumps(payload)}
                self.assertIsNone(await snapshot.load_snapshot(self.repository, now=now))

    async def test_complete_snapshot_retains_normal_cache_lifetime(self) -> None:
        now = datetime.now(UTC)
        self.payload["generated_at"] = (now - timedelta(minutes=60)).isoformat()
        self.repository.first.return_value = {"value": json.dumps(self.payload)}
        self.assertEqual(await snapshot.load_snapshot(self.repository, now=now), self.payload)

    async def test_snapshot_diagnostics_report_d1_and_parse_without_data(self) -> None:
        diagnostics: dict[str, float | str] = {}
        result = await snapshot.cached_brazil_dashboard(
            self.repository, diagnostics=diagnostics
        )
        self.assertEqual(result, self.payload)
        self.assertEqual(diagnostics["snapshot"], "fresh")
        self.assertGreaterEqual(diagnostics["d1_ms"], 0)
        self.assertGreaterEqual(diagnostics["parse_ms"], 0)
        self.assertNotIn("value", diagnostics)
        self.assertNotIn("metrics", diagnostics)

    async def test_missing_snapshot_reports_missing_without_expensive_work(self) -> None:
        self.repository.first.return_value = None
        diagnostics: dict[str, float | str] = {}
        with patch.object(snapshot, "build_dashboard", AsyncMock()) as build:
            result = await snapshot.cached_brazil_dashboard(
                self.repository, diagnostics=diagnostics
            )
        self.assertTrue(result["snapshot_unavailable"])
        self.assertEqual(diagnostics["snapshot"], "missing")
        self.assertIn("d1_ms", diagnostics)
        self.assertNotIn("parse_ms", diagnostics)
        build.assert_not_awaited()
