from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

LOCK_KEY = "cloudflare_refresh_writer_lock"
FULL_REFRESH_JOB_NAME = "cloudflare_full_refresh"
ORPHANED_FULL_REFRESH_REASON = (
    "Full refresh ended without finalizing job_run; reconciled as FAILED when the writer lock "
    "became available"
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _lease_expiry(now: datetime, ttl_seconds: int) -> str:
    return _iso(now + timedelta(seconds=max(60, int(ttl_seconds))))


async def _reconcile_orphaned_full_refresh_jobs(repository, *, finished_at: str) -> None:
    """Close full-refresh job rows that survived after their writer lease ended.

    This is only called after a new writer has atomically acquired the shared lock. At that
    point an older full refresh cannot still be the active writer, so any RUNNING full-refresh
    row that predates the new lease is orphaned rather than genuinely in progress.
    """
    await repository.run(
        """
        UPDATE job_runs
        SET finished_at=?,
            status='FAILED',
            error_message=COALESCE(NULLIF(error_message, ''), ?)
        WHERE job_name=?
          AND status='RUNNING'
          AND started_at < ?
        """,
        (
            finished_at,
            ORPHANED_FULL_REFRESH_REASON,
            FULL_REFRESH_JOB_NAME,
            finished_at,
        ),
    )


async def acquire_refresh_lock(
    repository,
    *,
    owner: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Acquire one advisory writer lock using an atomic runtime_state upsert.

    The lock protects the 30-minute fast path and the daily Workflow from writing market/
    NAV state at the same time. The expiry is embedded in a lexicographically sortable UTC
    timestamp so a crashed Workflow cannot block the system indefinitely.
    """
    clean_owner = owner.strip().replace("|", "-")[:160]
    if not clean_owner:
        raise ValueError("refresh lock owner cannot be empty")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    expires_iso = _lease_expiry(current, ttl_seconds)
    now_iso = _iso(current)
    token = f"{clean_owner}|{expires_iso}"

    await repository.run(
        """
        INSERT INTO runtime_state(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE instr(runtime_state.value, '|') = 0
           OR substr(runtime_state.value, instr(runtime_state.value, '|') + 1) <= ?
           OR runtime_state.value LIKE ?
        """,
        (LOCK_KEY, token, now_iso, f"{clean_owner}|%"),
    )
    row = await repository.first(
        "SELECT value, updated_at FROM runtime_state WHERE key=? LIMIT 1",
        (LOCK_KEY,),
    )
    actual = str(row.get("value") or "") if row else ""
    acquired = actual == token
    held_by = actual.split("|", 1)[0] if actual else None
    held_until = actual.split("|", 1)[1] if "|" in actual else None

    reconciliation_error = None
    if acquired:
        try:
            await _reconcile_orphaned_full_refresh_jobs(repository, finished_at=now_iso)
        except Exception as exc:
            # Housekeeping must never strand a newly acquired writer lock. The actual refresh
            # can still proceed, and a later lock acquisition will retry the reconciliation.
            reconciliation_error = f"{type(exc).__name__}: {str(exc)[:500]}"

    return {
        "acquired": acquired,
        "owner": clean_owner,
        "token": token if acquired else None,
        "expires_at": expires_iso if acquired else held_until,
        "held_by": clean_owner if acquired else held_by,
        "lock_key": LOCK_KEY,
        "orphan_reconciliation_error": reconciliation_error,
    }


async def renew_refresh_lock(
    repository,
    token: str | None,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Extend a writer lease only when the caller still owns the exact current token.

    Renewal is compare-and-swap: if another writer acquired the lock after expiry, the old
    token cannot overwrite the new owner. Callers must replace their local token with the
    returned token after every successful renewal.
    """
    if not token or "|" not in token:
        return {
            "renewed": False,
            "token": None,
            "owner": None,
            "expires_at": None,
            "reason": "missing_or_invalid_token",
            "lock_key": LOCK_KEY,
        }

    owner, _ = token.split("|", 1)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    expires_iso = _lease_expiry(current, ttl_seconds)
    renewed_token = f"{owner}|{expires_iso}"
    await repository.run(
        """
        UPDATE runtime_state
        SET value=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE key=? AND value=?
        """,
        (renewed_token, LOCK_KEY, token),
    )
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key=? LIMIT 1",
        (LOCK_KEY,),
    )
    actual = str(row.get("value") or "") if row else ""
    renewed = actual == renewed_token
    held_by = actual.split("|", 1)[0] if actual else None
    held_until = actual.split("|", 1)[1] if "|" in actual else None
    return {
        "renewed": renewed,
        "owner": owner,
        "token": renewed_token if renewed else None,
        "expires_at": expires_iso if renewed else held_until,
        "held_by": owner if renewed else held_by,
        "reason": None if renewed else "lease_lost",
        "lock_key": LOCK_KEY,
    }


async def release_refresh_lock(repository, token: str | None) -> bool:
    if not token:
        return False
    await repository.run(
        "DELETE FROM runtime_state WHERE key=? AND value=?",
        (LOCK_KEY, token),
    )
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key=? LIMIT 1",
        (LOCK_KEY,),
    )
    return row is None or str(row.get("value") or "") != token
