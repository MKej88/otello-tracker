from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.db.connection import get_connection
from app.discount_history import discount_history
from app.estimated_nav_history import ESTIMATED_NAV_CALCULATION_VERSION
from app.historical_investment_attribution import apply_historical_life360_change_split
from app.life360_nav import life360_market_value

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


def _latest_history_date(database_path: str | None) -> str | None:
    with get_connection(database_path) as connection:
        row = connection.execute(
            """SELECT MAX(date) AS max_date
               FROM estimated_nav_history_points
               WHERE calculation_version=? AND quality='VALID'""",
            (ESTIMATED_NAV_CALCULATION_VERSION,),
        ).fetchone()
    value = str((row["max_date"] if row else None) or "").strip()
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


def _enrich_life360_period(
    database_path: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Make Life360 period attribution available for every investor preset.

    The historical market-value series starts before Otello's separate fair-value
    presentation. Using the two period endpoints here means YTD/1Y/3Y get the same
    source-backed net effect as the short periods, while the helper keeps total NAV
    unchanged by reallocating any embedded historical amount from other ONA.
    """
    estimated = payload.get("estimated") if isinstance(payload, dict) else None
    change = estimated.get("change") if isinstance(estimated, dict) else None
    if not isinstance(change, dict) or not change.get("ready"):
        return payload

    start_date = str(change.get("resolved_start") or "").strip()
    current_date = str(change.get("current_date") or "").strip()
    if not start_date or not current_date:
        return payload

    start_state = life360_market_value(
        as_of_date=start_date,
        database_path=database_path,
    )
    current_state = life360_market_value(
        as_of_date=current_date,
        database_path=database_path,
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


def _load_entry(database_path: str | None, period_key: str) -> dict[str, Any] | None:
    with get_connection(database_path) as connection:
        row = connection.execute(
            "SELECT value, updated_at FROM runtime_state WHERE key=? LIMIT 1",
            (_cache_key(period_key),),
        ).fetchone()
    if row is None:
        return None
    try:
        entry = json.loads(str(row["value"] or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
        return None
    entry["updated_at"] = row["updated_at"]
    return entry


def materialize_discount_periods(database_path: str | None = None) -> dict[str, Any]:
    latest_history_date = _latest_history_date(database_path)
    if latest_history_date is None:
        return {
            "status": "skipped",
            "reason": "materialized_history_not_ready",
            "written": 0,
            "periods": [],
            "failures": [],
        }

    ready_entries: list[tuple[str, str]] = []
    failures: list[dict[str, Any]] = []
    for period_key, days, year_to_date in _period_specs(latest_history_date):
        try:
            payload = _enrich_life360_period(
                database_path,
                discount_history(
                    database_path,
                    days=days,
                    max_points=PERIOD_MAX_POINTS,
                    year_to_date=year_to_date,
                ),
            )
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
        value = json.dumps(
            {
                "period_key": period_key,
                "days": int(days),
                "year_to_date": bool(year_to_date),
                "max_points": PERIOD_MAX_POINTS,
                "source_date": latest_history_date,
                "calculation_version": PERIOD_CACHE_VERSION,
                "payload": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        ready_entries.append((_cache_key(period_key), value))

    if ready_entries:
        with get_connection(database_path) as connection:
            connection.executemany(
                """INSERT INTO runtime_state(key, value, updated_at)
                   VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                   ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value,
                       updated_at=excluded.updated_at""",
                ready_entries,
            )
            connection.commit()

    written = [key.rsplit(":", 1)[-1] for key, _ in ready_entries]
    return {
        "status": "ok" if not failures and len(written) == len(PERIOD_KEYS) else "partial",
        "source_date": latest_history_date,
        "calculation_version": PERIOD_CACHE_VERSION,
        "written": len(written),
        "periods": written,
        "failures": failures,
    }


def materialized_discount_history(
    database_path: str | None = None,
    *,
    days: int = 365,
    max_points: int = 600,
    year_to_date: bool = False,
) -> dict[str, Any]:
    period_key = _period_key(
        days=days,
        max_points=max_points,
        year_to_date=year_to_date,
    )
    if period_key is not None:
        latest_history_date = _latest_history_date(database_path)
        entry = _load_entry(database_path, period_key)
        if (
            latest_history_date is not None
            and entry is not None
            and entry.get("source_date") == latest_history_date
            and entry.get("calculation_version") == PERIOD_CACHE_VERSION
        ):
            return dict(entry["payload"])

    return _enrich_life360_period(
        database_path,
        discount_history(
            database_path,
            days=days,
            max_points=max_points,
            year_to_date=year_to_date,
        ),
    )


def materialized_nav_period_bundle(database_path: str | None = None) -> dict[str, Any]:
    latest_history_date = _latest_history_date(database_path)
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
        entry = _load_entry(database_path, period_key)
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
