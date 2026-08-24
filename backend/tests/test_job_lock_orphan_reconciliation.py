from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from job_lock import (  # noqa: E402
    LOCK_KEY,
    LOCK_STALE_HEARTBEAT_SECONDS,
    ORPHANED_REFRESH_REASON,
    acquire_refresh_lock,
)


class FakeRepository:
    def __init__(
        self,
        *,
        held_lock: str | None = None,
        held_updated_at: str | None = None,
    ) -> None:
        self.lock = held_lock
        self.updated_at = held_updated_at
        self.jobs = [
            {
                "id": 1,
                "job_name": "cloudflare_full_refresh",
                "started_at": "2026-08-21T03:35:55Z",
                "finished_at": None,
                "status": "RUNNING",
                "error_message": None,
            },
            {
                "id": 2,
                "job_name": "cloudflare_fast_refresh",
                "started_at": "2026-08-21T09:00:00Z",
                "finished_at": None,
                "status": "RUNNING",
                "error_message": None,
            },
            {
                "id": 3,
                "job_name": "cloudflare_fast_refresh",
                "started_at": "2026-08-21T09:30:00Z",
                "finished_at": None,
                "status": "RUNNING",
                "error_message": None,
            },
        ]

    async def run(self, sql: str, parameters=()):
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("INSERT INTO RUNTIME_STATE"):
            key, token, now_iso, stale_before_iso, owner_like = parameters
            assert key == LOCK_KEY
            clean_owner = owner_like.removesuffix("|%")
            if self.lock is None:
                self.lock = token
                self.updated_at = now_iso
            else:
                held_owner, separator, held_until = self.lock.partition("|")
                stale = self.updated_at is None or self.updated_at <= stale_before_iso
                if not separator or held_until <= now_iso or stale or held_owner == clean_owner:
                    self.lock = token
                    self.updated_at = now_iso
            return None

        if normalized.startswith("UPDATE JOB_RUNS"):
            finished_at, reason, full_job_name, fast_job_name, before = parameters
            for row in self.jobs:
                if (
                    row["job_name"] in {full_job_name, fast_job_name}
                    and row["status"] == "RUNNING"
                    and row["started_at"] < before
                ):
                    row["finished_at"] = finished_at
                    row["status"] = "FAILED"
                    if not row["error_message"]:
                        row["error_message"] = reason
            return None

        raise AssertionError(sql)

    async def first(self, sql: str, parameters=()):
        normalized = " ".join(sql.split()).upper()
        assert "FROM RUNTIME_STATE" in normalized
        assert parameters == (LOCK_KEY,)
        if self.lock is None:
            return None
        return {"value": self.lock, "updated_at": self.updated_at}


def test_acquiring_writer_lock_reconciles_orphaned_writer_jobs() -> None:
    repository = FakeRepository()
    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="fast:2026-08-21T09:30:00Z",
            ttl_seconds=20 * 60,
            now=datetime(2026, 8, 21, 9, 30, tzinfo=UTC),
        )
    )

    assert result["acquired"] is True
    assert result["orphan_reconciliation_error"] is None
    for row in repository.jobs[:2]:
        assert row["finished_at"] == "2026-08-21T09:30:00Z"
        assert row["status"] == "FAILED"
        assert row["error_message"] == ORPHANED_REFRESH_REASON

    # Same-timestamp retry/current fast job is not orphaned by strict started_at < finished_at.
    assert repository.jobs[2]["status"] == "RUNNING"
    assert repository.jobs[2]["finished_at"] is None


def test_failed_lock_acquisition_does_not_reconcile_writer_jobs() -> None:
    repository = FakeRepository(
        held_lock="full:2026-08-21:existing-instance|2026-08-21T12:00:00Z",
        held_updated_at="2026-08-21T09:20:00Z",
    )
    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="fast:2026-08-21T09:30:00Z",
            ttl_seconds=20 * 60,
            now=datetime(2026, 8, 21, 9, 30, tzinfo=UTC),
        )
    )

    assert result["acquired"] is False
    assert result["orphan_reconciliation_error"] is None
    assert all(row["status"] == "RUNNING" for row in repository.jobs)
    assert all(row["finished_at"] is None for row in repository.jobs)


def test_stale_heartbeat_can_recover_even_when_old_expiry_is_hours_away() -> None:
    assert LOCK_STALE_HEARTBEAT_SECONDS == 30 * 60
    repository = FakeRepository(
        held_lock="full:2026-08-24:dead-instance|2026-08-24T07:56:00Z",
        held_updated_at="2026-08-24T04:56:26Z",
    )
    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="fast:2026-08-24T05:30:00Z",
            ttl_seconds=20 * 60,
            now=datetime(2026, 8, 24, 5, 30, tzinfo=UTC),
        )
    )

    assert result["acquired"] is True
    assert result["held_by"] == "fast:2026-08-24T05:30:00Z"
    assert repository.jobs[0]["status"] == "FAILED"
    assert repository.jobs[0]["error_message"] == ORPHANED_REFRESH_REASON


def test_fresh_heartbeat_keeps_unexpired_lock_exclusive() -> None:
    repository = FakeRepository(
        held_lock="full:2026-08-24:live-instance|2026-08-24T07:56:00Z",
        held_updated_at="2026-08-24T05:10:00Z",
    )
    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="fast:2026-08-24T05:30:00Z",
            ttl_seconds=20 * 60,
            now=datetime(2026, 8, 24, 5, 30, tzinfo=UTC),
        )
    )

    assert result["acquired"] is False
    assert repository.jobs[0]["status"] == "RUNNING"
