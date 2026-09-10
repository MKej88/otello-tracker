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
