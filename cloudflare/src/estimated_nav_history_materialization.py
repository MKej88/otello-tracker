from __future__ import annotations

import json
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


async def materialize_estimated_nav_history_batch(
    repository,
    *,
    batch_size: int = 100,
    after_date: str | None = None,
) -> dict[str, Any]:
    """Materialize one cursor-bounded batch without letting invalid old dates block progress."""
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
            after_date,
            after_date,
            batch_size,
        ),
    )
    attempted = len(rows)
    next_cursor = str(rows[-1]["date"]) if rows else after_date
    written = 0
    failures: list[dict[str, Any]] = []

    for row in rows:
        day = str(row["date"])
        point = await _estimated_point(repository, day)
        if not point.get("ready"):
            failures.append({"date": day, "reason": point.get("reason")})
            continue
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
        written += 1

    return {
        "written": written,
        "attempted": attempted,
        "failures": failures,
        "batch_size": batch_size,
        "after_date": after_date,
        "next_cursor": next_cursor,
        "cursor_advanced": bool(rows) and next_cursor != after_date,
    }
