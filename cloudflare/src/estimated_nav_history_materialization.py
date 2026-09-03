from __future__ import annotations

import json
from datetime import date
from typing import Any

try:
    from .estimated_nav_history import (
        ESTIMATED_NAV_CALCULATION_VERSION,
        FULL_CALCULATION_VERSION,
        _estimated_point,
    )
except ImportError:
    from estimated_nav_history import (
        ESTIMATED_NAV_CALCULATION_VERSION,
        FULL_CALCULATION_VERSION,
        _estimated_point,
    )

SCAN_CURSOR_STATE_KEY = (
    f"estimated_nav_history_scan_cursor:{ESTIMATED_NAV_CALCULATION_VERSION}"
)
RETRY_BATCH_SIZE = 10
RETRY_DELAY_DAYS = 7


async def _load_scan_cursor(repository) -> str | None:
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key=? LIMIT 1",
        (SCAN_CURSOR_STATE_KEY,),
    )
    value = str((row or {}).get("value") or "").strip()
    if not value:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


async def _save_scan_cursor(repository, cursor: str | None) -> str | None:
    if not cursor:
        return await _load_scan_cursor(repository)
    date.fromisoformat(cursor)
    current = await _load_scan_cursor(repository)
    if current is not None and current >= cursor:
        return current
    await repository.run(
        """
        INSERT INTO runtime_state(key, value, updated_at)
        VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (SCAN_CURSOR_STATE_KEY, cursor),
    )
    return cursor


async def _write_point(repository, day: str, point: dict[str, Any]) -> None:
    await repository.run(
        """INSERT INTO estimated_nav_history_points (date, calculation_version,
           nav_total_mnok, nav_per_share_nok, otec_price_nok, discount_pct,
           shares_outstanding, accounting_nav_per_share_nok, composition_json,
           reconciliation_residual_mnok, quality, calculated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VALID',
                   strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
           ON CONFLICT(date, calculation_version) DO UPDATE SET
           nav_total_mnok=excluded.nav_total_mnok, nav_per_share_nok=excluded.nav_per_share_nok,
           otec_price_nok=excluded.otec_price_nok, discount_pct=excluded.discount_pct,
           shares_outstanding=excluded.shares_outstanding,
           accounting_nav_per_share_nok=excluded.accounting_nav_per_share_nok,
           composition_json=excluded.composition_json,
           reconciliation_residual_mnok=excluded.reconciliation_residual_mnok,
           quality='VALID', calculated_at=excluded.calculated_at""",
        (
            day,
            ESTIMATED_NAV_CALCULATION_VERSION,
            point["nav_total_mnok"],
            point["nav_per_share"],
            point["otec_price"],
            point["discount_pct"],
            point["shares_outstanding"],
            point["accounting_nav_per_share"],
            json.dumps(point["composition"], ensure_ascii=False, sort_keys=True),
            point["reconciliation_residual_mnok"],
        ),
    )


async def _remove_retry(repository, day: str) -> None:
    await repository.run(
        """DELETE FROM estimated_nav_history_retry_queue
           WHERE date=? AND calculation_version=?""",
        (day, ESTIMATED_NAV_CALCULATION_VERSION),
    )


async def _queue_failure(repository, day: str, reason: Any) -> None:
    failure_reason = str(reason or "not_ready")[:200]
    retry_modifier = f"+{RETRY_DELAY_DAYS} days"
    await repository.run(
        """INSERT INTO estimated_nav_history_retry_queue (
               date, calculation_version, reason, attempts,
               first_failed_at, last_failed_at, next_retry_at
           ) VALUES (
               ?, ?, ?, 1,
               strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               datetime('now', ?)
           )
           ON CONFLICT(date, calculation_version) DO UPDATE SET
               reason=excluded.reason,
               attempts=estimated_nav_history_retry_queue.attempts + 1,
               last_failed_at=excluded.last_failed_at,
               next_retry_at=excluded.next_retry_at""",
        (
            day,
            ESTIMATED_NAV_CALCULATION_VERSION,
            failure_reason,
            retry_modifier,
        ),
    )


async def _retry_due_failures(
    repository, *, batch_size: int = RETRY_BATCH_SIZE
) -> dict[str, Any]:
    """Retry a small, rate-limited queue without making old gaps part of the daily scan."""
    await repository.run(
        """DELETE FROM estimated_nav_history_retry_queue
           WHERE calculation_version=?
             AND EXISTS (
                 SELECT 1 FROM estimated_nav_history_points p
                 WHERE p.date=estimated_nav_history_retry_queue.date
                   AND p.calculation_version=estimated_nav_history_retry_queue.calculation_version
                   AND p.quality='VALID'
             )""",
        (ESTIMATED_NAV_CALCULATION_VERSION,),
    )
    rows = await repository.all(
        """SELECT date, reason, attempts, next_retry_at
           FROM estimated_nav_history_retry_queue
           WHERE calculation_version=?
             AND next_retry_at <= strftime('%Y-%m-%dT%H:%M:%fZ','now')
           ORDER BY next_retry_at, date
           LIMIT ?""",
        (ESTIMATED_NAV_CALCULATION_VERSION, max(1, int(batch_size))),
    )

    written = 0
    failures: list[dict[str, Any]] = []
    for row in rows:
        day = str(row["date"])
        point = await _estimated_point(repository, day)
        if point.get("ready"):
            await _write_point(repository, day, point)
            await _remove_retry(repository, day)
            written += 1
            continue
        reason = point.get("reason")
        failures.append({"date": day, "reason": reason})
        await _queue_failure(repository, day, reason)

    pending_row = await repository.first(
        """SELECT COUNT(*) AS count
           FROM estimated_nav_history_retry_queue
           WHERE calculation_version=?""",
        (ESTIMATED_NAV_CALCULATION_VERSION,),
    )
    return {
        "attempted": len(rows),
        "written": written,
        "failures": failures,
        "pending": int((pending_row or {}).get("count") or 0),
        "batch_size": max(1, int(batch_size)),
        "retry_delay_days": RETRY_DELAY_DAYS,
    }


async def materialize_estimated_nav_history_batch(
    repository,
    *,
    batch_size: int = 100,
    after_date: str | None = None,
) -> dict[str, Any]:
    """Materialize one bounded batch and persist scan progress across nightly runs."""
    if after_date is not None:
        date.fromisoformat(after_date)
    persistent_cursor = await _load_scan_cursor(repository)
    effective_after_date = max(
        (value for value in (after_date, persistent_cursor) if value is not None),
        default=None,
    )
    rows = await repository.all(
        """SELECT DISTINCT substr(n.as_of_at, 1, 10) AS date
           FROM nav_snapshots n
           LEFT JOIN estimated_nav_history_points p
             ON p.date=substr(n.as_of_at, 1, 10)
            AND p.calculation_version=? AND p.quality='VALID'
           WHERE n.calculation_version=? AND n.nav_scope='FULL' AND p.date IS NULL
             AND (? IS NULL OR substr(n.as_of_at, 1, 10) > ?)
           ORDER BY date LIMIT ?""",
        (
            ESTIMATED_NAV_CALCULATION_VERSION,
            FULL_CALCULATION_VERSION,
            effective_after_date,
            effective_after_date,
            batch_size,
        ),
    )
    attempted = len(rows)
    next_cursor = str(rows[-1]["date"]) if rows else effective_after_date
    written = 0
    failures: list[dict[str, Any]] = []

    for row in rows:
        day = str(row["date"])
        point = await _estimated_point(repository, day)
        if not point.get("ready"):
            reason = point.get("reason")
            failures.append({"date": day, "reason": reason})
            await _queue_failure(repository, day, reason)
            continue
        await _write_point(repository, day, point)
        await _remove_retry(repository, day)
        written += 1

    persisted_cursor_after = await _save_scan_cursor(repository, next_cursor)
    retry = (
        await _retry_due_failures(repository)
        if attempted < batch_size
        else {
            "attempted": 0,
            "written": 0,
            "failures": [],
            "pending": None,
            "batch_size": RETRY_BATCH_SIZE,
            "retry_delay_days": RETRY_DELAY_DAYS,
            "deferred": True,
        }
    )

    return {
        "written": written,
        "attempted": attempted,
        "failures": failures,
        "batch_size": batch_size,
        "requested_after_date": after_date,
        "after_date": effective_after_date,
        "persistent_cursor_before": persistent_cursor,
        "next_cursor": next_cursor,
        "persistent_cursor_after": persisted_cursor_after,
        "cursor_advanced": bool(rows) and next_cursor != effective_after_date,
        "retry": retry,
    }
