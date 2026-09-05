from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

try:
    from .discount_history import discount_history
    from .estimated_nav_history import ESTIMATED_NAV_CALCULATION_VERSION
    from .historical_investment_attribution import apply_historical_life360_change_split
    from .life360_nav import life360_market_value
except ImportError:
    from discount_history import discount_history
    from estimated_nav_history import ESTIMATED_NAV_CALCULATION_VERSION
    from historical_investment_attribution import apply_historical_life360_change_split
    from life360_nav import life360_market_value

PERIOD_CACHE_VERSION = f"{ESTIMATED_NAV_CALCULATION_VERSION}:NAV_PERIODS_V3"
PERIOD_CACHE_KEY_PREFIX = "materialized_discount_period"
PERIOD_MAX_POINTS = 72
_FIXED_PERIOD_DAYS = {
    "1m": 31,
    "3m": 92,
    "6m": 183,
    "1y": 365,
    "3y": 1095,
}
PERIOD_KEYS = ("1m", "3m", "6m", "ytd", "1y", "3y")


def _cache_key(period_key: str) -> str:
    return f"{PERIOD_CACHE_KEY_PREFIX}:{PERIOD_CACHE_VERSION}:{period_key}"


def _period_key(*, days: int, max_points: int, year_to_date: bool) -> str | None:
    if int(max_points) != PERIOD_MAX_POINTS:
        return None
    if year_to_date:
        return "ytd"
    normalized_days = int(days)
    for key, period_days in _FIXED_PERIOD_DAYS.items():
        if normalized_days == period_days:
            return key
    return None


async def _latest_history_date(repository) -> str | None:
    row = await repository.first(
        """SELECT MAX(date) AS max_date
           FROM estimated_nav_history_points
           WHERE calculation_version=? AND quality='VALID'""",
        (ESTIMATED_NAV_CALCULATION_VERSION,),
    )
    value = str((row or {}).get("max_date") or "").strip()
    return value or None


def _ytd_days(latest_history_date: str) -> int:
    current = date.fromisoformat(latest_history_date)
    return max(30, (current - date(current.year, 1, 1)).days + 1)


def _period_specs(latest_history_date: str) -> tuple[tuple[str, int, bool], ...]:
    return (
        ("1m", 31, False),
        ("3m", 92, False),
        ("6m", 183, False),
        ("ytd", _ytd_days(latest_history_date), True),
        ("1y", 365, False),
        ("3y", 1095, False),
    )


async def _enrich_life360_period(repository, payload: dict[str, Any]) -> dict[str, Any]:
    """Make source-backed Life360 net effect available for every investor preset."""
    estimated = payload.get("estimated") if isinstance(payload, dict) else None
    change = estimated.get("change") if isinstance(estimated, dict) else None
    if not isinstance(change, dict) or not change.get("ready"):
        return payload

    start_date = str(change.get("resolved_start") or "").strip()
    current_date = str(change.get("current_date") or "").strip()
    if not start_date or not current_date:
        return payload

    start_state, current_state = await asyncio.gather(
        life360_market_value(repository, as_of_date=start_date),
        life360_market_value(repository, as_of_date=current_date),
    )
    if not apply_historical_life360_change_split(change, start_state, current_state):
        change["life360_period_attribution_status"] = {
            "ready": False,
            "start_reason": start_state.get("reason"),
            "current_reason": current_state.get("reason"),
        }
    else:
        change["life360_period_attribution_status"] = {
            "ready": True,
            "start_date": start_state.get("as_of_date"),
            "current_date": current_state.get("as_of_date"),
        }
    return payload


def _decode_entry(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        entry = json.loads(str(row.get("value") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict):
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    entry["updated_at"] = row.get("updated_at")
    return entry


async def _load_entry(repository, period_key: str) -> dict[str, Any] | None:
    row = await repository.first(
        "SELECT value, updated_at FROM runtime_state WHERE key=? LIMIT 1",
        (_cache_key(period_key),),
    )
    return _decode_entry(row)


async def _write_entry(
    repository,
    *,
    period_key: str,
    days: int,
    year_to_date: bool,
    source_date: str,
    payload: dict[str, Any],
) -> None:
    value = json.dumps(
        {
            "period_key": period_key,
            "days": int(days),
            "year_to_date": bool(year_to_date),
            "max_points": PERIOD_MAX_POINTS,
            "source_date": source_date,
            "calculation_version": PERIOD_CACHE_VERSION,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    await repository.run(
        """INSERT INTO runtime_state(key, value, updated_at)
           VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT(key) DO UPDATE SET
               value=excluded.value,
               updated_at=excluded.updated_at""",
        (_cache_key(period_key), value),
    )


async def materialize_discount_periods(repository) -> dict[str, Any]:
    """Precompute the six investor periods after nightly NAV history is complete."""
    latest_history_date = await _latest_history_date(repository)
    if latest_history_date is None:
        return {
            "status": "skipped",
            "reason": "materialized_history_not_ready",
            "written": 0,
            "periods": [],
            "failures": [],
        }

    written: list[str] = []
    failures: list[dict[str, Any]] = []
    for period_key, days, year_to_date in _period_specs(latest_history_date):
        try:
            payload = await discount_history(
                repository,
                days=days,
                max_points=PERIOD_MAX_POINTS,
                year_to_date=year_to_date,
            )
            payload = await _enrich_life360_period(repository, payload)
        except Exception as exc:
            failures.append(
                {
                    "period_key": period_key,
                    "reason": str(exc)[:500] or type(exc).__name__,
                    "error_type": type(exc).__name__,
                }
            )
            continue

        estimated = payload.get("estimated") if isinstance(payload, dict) else None
        estimated_to = str((estimated or {}).get("to") or "").strip()
        if not isinstance(estimated, dict) or not estimated.get("ready"):
            failures.append(
                {
                    "period_key": period_key,
                    "reason": (estimated or {}).get("reason") or "estimated_period_not_ready",
                }
            )
            continue
        if estimated_to != latest_history_date:
            failures.append(
                {
                    "period_key": period_key,
                    "reason": "estimated_period_not_current",
                    "expected_source_date": latest_history_date,
                    "actual_source_date": estimated_to or None,
                }
            )
            continue

        await _write_entry(
            repository,
            period_key=period_key,
            days=days,
            year_to_date=year_to_date,
            source_date=latest_history_date,
            payload=payload,
        )
        written.append(period_key)

    return {
        "status": "ok" if not failures and len(written) == len(PERIOD_KEYS) else "partial",
        "source_date": latest_history_date,
        "calculation_version": PERIOD_CACHE_VERSION,
        "written": len(written),
        "periods": written,
        "failures": failures,
    }


async def materialized_discount_history(
    repository,
    *,
    days: int = 365,
    max_points: int = 600,
    year_to_date: bool = False,
) -> dict[str, Any]:
    """Serve a nightly precomputed preset when fresh, otherwise preserve live fallback."""
    period_key = _period_key(
        days=days,
        max_points=max_points,
        year_to_date=year_to_date,
    )
    if period_key is not None:
        latest_history_date = await _latest_history_date(repository)
        entry = await _load_entry(repository, period_key)
        if (
            latest_history_date is not None
            and entry is not None
            and entry.get("source_date") == latest_history_date
            and entry.get("calculation_version") == PERIOD_CACHE_VERSION
        ):
            return dict(entry["payload"])

    payload = await discount_history(
        repository,
        days=days,
        max_points=max_points,
        year_to_date=year_to_date,
    )
    return await _enrich_life360_period(repository, payload)


async def materialized_nav_period_bundle(repository) -> dict[str, Any]:
    """Return every precomputed NAV period in one small payload for instant UI switching."""
    latest_history_date = await _latest_history_date(repository)
    if latest_history_date is None:
        return {
            "ready": False,
            "reason": "materialized_history_not_ready",
            "periods": {},
            "missing_periods": list(PERIOD_KEYS),
            "calculation_version": PERIOD_CACHE_VERSION,
        }

    periods: dict[str, Any] = {}
    updated_at_values: list[str] = []
    missing: list[str] = []
    for period_key in PERIOD_KEYS:
        entry = await _load_entry(repository, period_key)
        if (
            entry is None
            or entry.get("source_date") != latest_history_date
            or entry.get("calculation_version") != PERIOD_CACHE_VERSION
        ):
            missing.append(period_key)
            continue
        payload = entry.get("payload") or {}
        estimated = payload.get("estimated") if isinstance(payload, dict) else None
        if not isinstance(estimated, dict) or not estimated.get("ready"):
            missing.append(period_key)
            continue
        periods[period_key] = estimated
        if entry.get("updated_at"):
            updated_at_values.append(str(entry["updated_at"]))

    return {
        "ready": not missing,
        "source_date": latest_history_date,
        "calculation_version": PERIOD_CACHE_VERSION,
        "calculated_at": max(updated_at_values) if updated_at_values else None,
        "periods": periods,
        "missing_periods": missing,
    }
