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
            "metrics": {"selic": {"value": 15}},
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

    async def test_cache_miss_seeds_snapshot_for_next_visitor(self) -> None:
        self.repository.first.return_value = None
        with patch.object(snapshot, "build_dashboard", AsyncMock(return_value=self.payload)):
            self.assertEqual(await snapshot.cached_brazil_dashboard(self.repository), self.payload)
        stored = self.repository.run.await_args.args[1]
        self.assertEqual(stored[0], snapshot.STATE_KEY)
        self.assertEqual(json.loads(stored[1]), self.payload)

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

    async def test_cron_refresh_updates_snapshot(self) -> None:
        with patch.object(snapshot, "build_dashboard", AsyncMock(return_value=self.payload)):
            result = await snapshot.refresh_brazil_snapshot(self.repository)
        self.assertEqual(result["status"], "ok")
        self.repository.run.assert_awaited_once()

    async def test_cache_storage_failure_still_returns_live_response(self) -> None:
        self.repository.first.side_effect = RuntimeError("database unavailable")
        self.repository.run.side_effect = RuntimeError("database unavailable")
        with patch.object(snapshot, "build_dashboard", AsyncMock(return_value=self.payload)):
            self.assertEqual(await snapshot.cached_brazil_dashboard(self.repository), self.payload)
