from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

STATE_PREFIX = "norges_bank_nav_history_v1:"


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


async def history_window_complete(repository, *, start_date: str, end_date: str) -> bool:
    year = date.fromisoformat(start_date).year
    if date.fromisoformat(end_date).year != year:
        raise ValueError("history_window_complete krever ett kalenderår")
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key=? LIMIT 1",
        (_key(year),),
    )
    marker = _parse_marker((row or {}).get("value"))
    return bool(marker and marker[0] <= start_date and marker[1] >= end_date)


async def mark_history_window_complete(repository, *, start_date: str, end_date: str) -> None:
    year = date.fromisoformat(start_date).year
    if date.fromisoformat(end_date).year != year:
        raise ValueError("mark_history_window_complete krever ett kalenderår")
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key=? LIMIT 1",
        (_key(year),),
    )
    existing = _parse_marker((row or {}).get("value"))
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

    for year, window_start, window_end in _windows(required_start, required_end.isoformat()):
        marker = markers.get(year)
        if marker is None or marker[0] > window_start or marker[1] < window_end:
            return True
    return False
