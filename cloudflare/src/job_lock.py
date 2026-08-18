from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

LOCK_KEY = "cloudflare_refresh_writer_lock"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    expires = current + timedelta(seconds=max(60, int(ttl_seconds)))
    now_iso = _iso(current)
    expires_iso = _iso(expires)
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
    return {
        "acquired": acquired,
        "owner": clean_owner,
        "token": token if acquired else None,
        "expires_at": expires_iso if acquired else held_until,
        "held_by": clean_owner if acquired else held_by,
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
