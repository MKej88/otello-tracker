from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from src.job_lock import (
    FAST_REFRESH_JOB_NAME,
    FULL_REFRESH_JOB_NAME,
    LOCK_KEY,
    ORPHANED_REFRESH_REASON,
    acquire_refresh_lock,
    release_refresh_lock,
    renew_refresh_lock,
    renew_workflow_refresh_lock,
    release_workflow_refresh_lock,
)


class LockRepository:
    def __init__(
        self,
        value: str | None,
        *,
        updated_at: str = "2026-09-10T11:59:00Z",
        running_jobs: list[dict[str, str | None]] | None = None,
    ) -> None:
        self.value = value
        self.updated_at = updated_at
        self.running_jobs = running_jobs or []

    async def run(self, _sql: str, parameters: tuple[Any, ...]) -> None:
        normalized_sql = " ".join(_sql.split())
        if normalized_sql.startswith("DELETE FROM runtime_state"):
            key, token = parameters
            if key == LOCK_KEY and self.value == token:
                self.value = None
            return

        if normalized_sql.startswith("INSERT INTO runtime_state"):
            key, token, now, stale_before, owner_pattern = parameters
            owner_prefix = owner_pattern.removesuffix("%")
            expires_at = (
                self.value.split("|", 1)[1] if self.value and "|" in self.value else ""
            )
            can_acquire = (
                self.value is None
                or "|" not in self.value
                or expires_at <= now
                or self.updated_at <= stale_before
                or self.value.startswith(owner_prefix)
            )
            if key == LOCK_KEY and can_acquire:
                self.value = token
                self.updated_at = now
            return

        if normalized_sql.startswith("UPDATE runtime_state"):
            renewed_token, key, previous_token = parameters
            if key == LOCK_KEY and self.value == previous_token:
                self.value = renewed_token
            return

        if normalized_sql.startswith("UPDATE job_runs"):
            finished_at, reason, *job_names, started_before = parameters
            for job in self.running_jobs:
                if (
                    job["job_name"] in job_names
                    and job["status"] == "RUNNING"
                    and str(job["started_at"]) < started_before
                ):
                    job["status"] = "FAILED"
                    job["finished_at"] = finished_at
                    if not job.get("error_message"):
                        job["error_message"] = reason
            return

        raise AssertionError(f"Unexpected SQL: {normalized_sql}")

    async def first(
        self,
        _sql: str,
        _parameters: tuple[Any, ...],
    ) -> dict[str, str] | None:
        return (
            {"value": self.value, "updated_at": self.updated_at}
            if self.value is not None
            else None
        )


def test_acquire_does_not_replace_an_active_lock_from_another_writer() -> None:
    repository = LockRepository(
        "full:existing|2026-09-10T13:00:00Z",
        updated_at="2026-09-10T11:59:00Z",
    )

    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="fast:new",
            ttl_seconds=600,
            now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        )
    )

    assert result["acquired"] is False
    assert result["held_by"] == "full:existing"
    assert result["expires_at"] == "2026-09-10T13:00:00Z"
    assert repository.value == "full:existing|2026-09-10T13:00:00Z"


def test_acquire_retry_by_same_owner_refreshes_its_active_lock() -> None:
    repository = LockRepository(
        "full:workflow-instance|2026-09-10T13:00:00Z",
        updated_at="2026-09-10T11:59:00Z",
    )

    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="full:workflow-instance",
            ttl_seconds=600,
            now=datetime(2026, 9, 10, 12, 5, tzinfo=UTC),
        )
    )

    assert result["acquired"] is True
    assert result["token"] == "full:workflow-instance|2026-09-10T12:15:00Z"
    assert result["held_by"] == "full:workflow-instance"
    assert repository.value == result["token"]


def test_acquire_replaces_expired_lock_and_closes_only_older_writer_jobs() -> None:
    running_jobs = [
        {
            "job_name": FULL_REFRESH_JOB_NAME,
            "status": "RUNNING",
            "started_at": "2026-09-10T11:00:00Z",
            "finished_at": None,
            "error_message": None,
        },
        {
            "job_name": FAST_REFRESH_JOB_NAME,
            "status": "RUNNING",
            "started_at": "2026-09-10T12:00:00Z",
            "finished_at": None,
            "error_message": None,
        },
    ]
    repository = LockRepository(
        "full:expired|2026-09-10T12:00:00Z",
        running_jobs=running_jobs,
    )

    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="fast:replacement",
            ttl_seconds=600,
            now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        )
    )

    assert result["acquired"] is True
    assert result["token"] == "fast:replacement|2026-09-10T12:10:00Z"
    assert running_jobs[0] == {
        "job_name": FULL_REFRESH_JOB_NAME,
        "status": "FAILED",
        "started_at": "2026-09-10T11:00:00Z",
        "finished_at": "2026-09-10T12:00:00Z",
        "error_message": ORPHANED_REFRESH_REASON,
    }
    assert running_jobs[1]["status"] == "RUNNING"
    assert running_jobs[1]["finished_at"] is None


def test_acquire_recovers_unexpired_lock_with_stale_heartbeat() -> None:
    running_jobs = [
        {
            "job_name": FAST_REFRESH_JOB_NAME,
            "status": "RUNNING",
            "started_at": "2026-09-10T11:00:00Z",
            "finished_at": None,
            "error_message": None,
        }
    ]
    repository = LockRepository(
        "fast:abandoned|2026-09-10T15:00:00Z",
        updated_at="2026-09-10T11:29:59Z",
        running_jobs=running_jobs,
    )

    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="full:replacement",
            ttl_seconds=600,
            now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        )
    )

    assert result["acquired"] is True
    assert result["token"] == "full:replacement|2026-09-10T12:10:00Z"
    assert running_jobs[0]["status"] == "FAILED"
    assert running_jobs[0]["finished_at"] == "2026-09-10T12:00:00Z"
    assert running_jobs[0]["error_message"] == ORPHANED_REFRESH_REASON


def test_acquired_lock_survives_orphan_reconciliation_failure() -> None:
    class FailingReconciliationRepository(LockRepository):
        async def run(self, sql: str, parameters: tuple[Any, ...]) -> None:
            if "UPDATE job_runs" in sql:
                raise RuntimeError("job_runs is temporarily unavailable")
            await super().run(sql, parameters)

    repository = FailingReconciliationRepository(None)

    result = asyncio.run(
        acquire_refresh_lock(
            repository,
            owner="fast:new",
            ttl_seconds=600,
            now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        )
    )

    assert result["acquired"] is True
    assert result["token"] == "fast:new|2026-09-10T12:10:00Z"
    assert result["orphan_reconciliation_error"] == (
        "RuntimeError: job_runs is temporarily unavailable"
    )
    assert repository.value == result["token"]


def test_renew_does_not_overwrite_a_lock_taken_over_by_another_writer() -> None:
    stale_token = "fast:old|2026-09-10T12:00:00Z"
    current_token = "full:new|2026-09-10T13:00:00Z"
    repository = LockRepository(current_token)

    result = asyncio.run(
        renew_refresh_lock(
            repository,
            stale_token,
            ttl_seconds=600,
            now=datetime(2026, 9, 10, 12, 5, tzinfo=UTC),
        )
    )

    assert result["renewed"] is False
    assert result["reason"] == "lease_lost"
    assert result["held_by"] == "full:new"
    assert result["expires_at"] == "2026-09-10T13:00:00Z"
    assert repository.value == current_token


def test_release_reports_success_when_owned_lock_is_deleted() -> None:
    token = "full:2026-08-30:workflow|2026-08-30T04:00:00Z"
    repository = LockRepository(token)

    assert asyncio.run(release_refresh_lock(repository, token)) is True
    assert repository.value is None


def test_release_reports_failure_when_another_owner_holds_lock() -> None:
    stale_token = "full:2026-08-30:workflow|2026-08-30T04:00:00Z"
    current_token = "fast:2026-08-30T04:30:00Z|2026-08-30T05:00:00Z"
    repository = LockRepository(current_token)

    assert asyncio.run(release_refresh_lock(repository, stale_token)) is False
    assert repository.value == current_token


class SQLiteLeaseRepository:
    """Execute production SQL, including atomic ownership guards."""
    def __init__(self, value, heartbeat):
        import sqlite3
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE runtime_state (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        )
        if value is not None:
            self.connection.execute(
                "INSERT INTO runtime_state VALUES (?, ?, ?)", (LOCK_KEY, value, heartbeat)
            )
        self.fail_after_write = False
        self.takeover_before_write = None

    async def run(self, sql, parameters=()):
        if self.takeover_before_write is not None:
            self.connection.execute(
                "UPDATE runtime_state SET value=? WHERE key=?",
                (self.takeover_before_write, LOCK_KEY),
            )
            self.takeover_before_write = None
        self.connection.execute(sql, parameters)
        self.connection.commit()
        if self.fail_after_write:
            self.fail_after_write = False
            raise MemoryError("simulated interruption after committed D1 UPDATE")

    async def first(self, sql, parameters=()):
        row = self.connection.execute(sql, parameters).fetchone()
        return dict(row) if row else None


def test_workflow_renewal_recovers_after_committed_update_and_lost_result():
    from datetime import timedelta
    now = datetime.now(UTC).replace(microsecond=0)
    owner = "full:2026-11-25:unique-instance"
    iso = lambda value: value.isoformat().replace("+00:00", "Z")
    original = f"{owner}|{iso(now + timedelta(hours=1))}"
    repository = SQLiteLeaseRepository(original, iso(now))
    repository.fail_after_write = True

    async def exercise():
        try:
            await renew_workflow_refresh_lock(
                repository, original, owner=owner, ttl_seconds=10800, now=now,
            )
        except MemoryError:
            pass
        else:
            raise AssertionError("Expected simulated post-commit interruption")
        recovered = await renew_workflow_refresh_lock(
            repository, original, owner=owner, ttl_seconds=10800,
            now=now + timedelta(seconds=5),
        )
        assert recovered["renewed"] and recovered["recovered_same_owner"]
        assert recovered["token"] == f"{owner}|{iso(now + timedelta(hours=3, seconds=5))}"
        assert await release_workflow_refresh_lock(repository, original, owner=owner)
        assert await repository.first("SELECT value FROM runtime_state WHERE key=?", (LOCK_KEY,)) is None

    asyncio.run(exercise())


def test_workflow_renewal_never_recovers_expired_stale_or_other_owner():
    from datetime import timedelta
    now = datetime.now(UTC).replace(microsecond=0)
    owner = "full:2026-11-25:unique-instance"
    iso = lambda value: value.isoformat().replace("+00:00", "Z")
    original = f"{owner}|{iso(now + timedelta(hours=1))}"
    cases = [
        (f"full:other|{iso(now + timedelta(hours=2))}", iso(now)),
        (f"{owner}|{iso(now - timedelta(seconds=1))}", iso(now)),
        (original, iso(now - timedelta(minutes=31))),
        (f"{owner}|{iso(now + timedelta(minutes=30))}", iso(now)),
        (None, iso(now)),
    ]
    for value, heartbeat in cases:
        repository = SQLiteLeaseRepository(value, heartbeat)
        result = asyncio.run(renew_workflow_refresh_lock(
            repository, original, owner=owner, ttl_seconds=10800, now=now,
        ))
        assert not result["renewed"]
        row = asyncio.run(repository.first("SELECT value FROM runtime_state WHERE key=?", (LOCK_KEY,)))
        assert (row or {}).get("value") == value


def test_workflow_renewal_and_cleanup_cannot_overwrite_concurrent_takeover():
    from datetime import timedelta
    now = datetime.now(UTC).replace(microsecond=0)
    owner = "full:2026-11-25:unique-instance"
    iso = lambda value: value.isoformat().replace("+00:00", "Z")
    original = f"{owner}|{iso(now + timedelta(hours=1))}"
    replacement = f"fast:other|{iso(now + timedelta(hours=2))}"
    repository = SQLiteLeaseRepository(original, iso(now))
    repository.takeover_before_write = replacement
    result = asyncio.run(renew_workflow_refresh_lock(
        repository, original, owner=owner, ttl_seconds=10800, now=now,
    ))
    assert not result["renewed"]
    assert result["held_by"] == "fast:other"
    assert not asyncio.run(release_workflow_refresh_lock(repository, original, owner=owner))
    repository = SQLiteLeaseRepository(original, iso(now))
    repository.takeover_before_write = replacement
    assert not asyncio.run(release_workflow_refresh_lock(repository, original, owner=owner))
    row = asyncio.run(repository.first("SELECT value FROM runtime_state WHERE key=?", (LOCK_KEY,)))
    assert row["value"] == replacement
