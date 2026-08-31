from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

STATE_PREFIX = "norges_bank_nav_history_v1:"
HISTORY_REBUILD_CHUNK_DAYS = 31


def _key(year: int) -> str:
    return f"{STATE_PREFIX}{year}"


def _windows(start_date: str, end_date: str) -> list[tuple[int, str, str]]:
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if current > end:
        return []
    windows: list[tuple[int, str, str]] = []
    while current <= end:
        year_end = min(date(current.year, 12, 31), end)
        windows.append((current.year, current.isoformat(), year_end.isoformat()))
        current = year_end + timedelta(days=1)
    return windows


def _parse_marker(value: Any) -> tuple[str, str] | None:
    if not value:
        return None
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    start = str(payload.get("from") or "")
    end = str(payload.get("to") or "")
    try:
        date.fromisoformat(start)
        date.fromisoformat(end)
    except ValueError:
        return None
    return start, end


def _calendar_year(start_date: str, end_date: str, *, operation: str) -> int:
    """Validate that a checkpoint window belongs to one calendar year."""
    year = date.fromisoformat(start_date).year
    if date.fromisoformat(end_date).year != year:
        raise ValueError(f"{operation} krever ett kalenderår")
    return year


async def _load_marker(repository, year: int) -> tuple[str, str] | None:
    """Load and validate the single checkpoint representation used by all operations."""
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key=? LIMIT 1",
        (_key(year),),
    )
    return _parse_marker((row or {}).get("value"))


async def history_window_complete(
    repository, *, start_date: str, end_date: str
) -> bool:
    year = _calendar_year(
        start_date,
        end_date,
        operation="history_window_complete",
    )
    marker = await _load_marker(repository, year)
    return bool(marker and marker[0] <= start_date and marker[1] >= end_date)


async def next_history_rebuild_chunk(
    repository,
    *,
    start_date: str,
    end_date: str,
    max_days: int = HISTORY_REBUILD_CHUNK_DAYS,
) -> tuple[str, str] | None:
    """Return the next contiguous, bounded part of one calendar-year rebuild.

    The checkpoint is deliberately contiguous from ``start_date``. This lets a killed Worker
    resume on the next full refresh without repeating a whole year and without letting a later
    successful chunk accidentally bridge across an unprocessed gap.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    year = _calendar_year(
        start_date,
        end_date,
        operation="next_history_rebuild_chunk",
    )
    if start > end:
        return None
    days = max(1, int(max_days))
    marker = await _load_marker(repository, year)
    next_start = start
    if marker:
        marker_start = date.fromisoformat(marker[0])
        marker_end = date.fromisoformat(marker[1])
        if marker_start <= start <= marker_end:
            next_start = marker_end + timedelta(days=1)
        elif marker_start > start:
            raise ValueError(
                "Historisk NAV-checkpoint er ikke sammenhengende fra vinduets start"
            )
    if next_start > end:
        return None
    next_end = min(end, next_start + timedelta(days=days - 1))
    return next_start.isoformat(), next_end.isoformat()


async def mark_history_window_complete(
    repository, *, start_date: str, end_date: str
) -> None:
    year = _calendar_year(
        start_date,
        end_date,
        operation="mark_history_window_complete",
    )
    existing = await _load_marker(repository, year)
    if existing:
        existing_start = date.fromisoformat(existing[0])
        existing_end = date.fromisoformat(existing[1])
        incoming_start = date.fromisoformat(start_date)
        incoming_end = date.fromisoformat(end_date)
        if incoming_start > existing_end + timedelta(
            days=1
        ) or incoming_end < existing_start - timedelta(days=1):
            raise ValueError(
                "Historisk NAV-checkpoint kan ikke slå sammen ikke-sammenhengende vinduer"
            )
    covered_from = min(start_date, existing[0]) if existing else start_date
    covered_to = max(end_date, existing[1]) if existing else end_date
    value = json.dumps(
        {"from": covered_from, "to": covered_to},
        sort_keys=True,
        separators=(",", ":"),
    )
    await repository.run(
        """
        INSERT INTO runtime_state(key, value, updated_at)
        VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (_key(year), value),
    )


async def history_rebuild_needed(
    repository,
    *,
    required_start: str,
    target_date: str,
) -> bool:
    """Return True until checkpoints cover history through the day before target.

    The normal daily NAV refresh handles target_date itself, so the historical bootstrap only
    needs to be complete through target_date - 1. This prevents a completed bootstrap from
    re-running every day merely because the rolling target advanced by one day.
    """
    target = date.fromisoformat(target_date)
    required_end = target - timedelta(days=1)
    if date.fromisoformat(required_start) > required_end:
        return False

    rows = await repository.all(
        "SELECT key, value FROM runtime_state WHERE key LIKE ?",
        (f"{STATE_PREFIX}%",),
    )
    markers: dict[int, tuple[str, str]] = {}
    for row in rows:
        key = str(row.get("key") or "")
        try:
            year = int(key.removeprefix(STATE_PREFIX))
        except ValueError:
            continue
        marker = _parse_marker(row.get("value"))
        if marker:
            markers[year] = marker

    for year, window_start, window_end in _windows(
        required_start, required_end.isoformat()
    ):
        marker = markers.get(year)
        if marker is None or marker[0] > window_start or marker[1] < window_end:
            return True
    return False
