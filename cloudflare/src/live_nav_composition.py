from __future__ import annotations

from typing import Any

from estimated_nav_history import _estimated_point
from estimated_nav_history_display import _split_current_composition
from life360_nav import life360_nav_adjustment


async def live_nav_composition(repository: Any, day: str) -> dict[str, Any]:
    """Build one current investor-NAV composition without calculating period attribution.

    The calculation deliberately reuses the same one-day point and display split as the
    materialized history. This keeps the live composition mathematically identical to the
    investor NAV while the heavier multi-period attribution can remain nightly materialized.
    """
    point = await _estimated_point(repository, day)
    if not point.get("ready"):
        return {
            "ready": False,
            "reason": point.get("reason") or "live_composition_point_not_ready",
            "date": day,
        }

    life360_state = await life360_nav_adjustment(repository, as_of_date=day)
    split_ready = await _split_current_composition(repository, point, life360_state)
    return {
        "ready": True,
        "date": str(point.get("date") or day),
        "nav_total_mnok": point.get("nav_total_mnok"),
        "nav_per_share": point.get("nav_per_share"),
        "shares_outstanding": point.get("shares_outstanding"),
        "composition": point.get("composition") or [],
        "reconciliation_residual_mnok": point.get("reconciliation_residual_mnok"),
        "composition_split_status": point.get("composition_split_status"),
        "display_policy": (
            "REPORT_CASH_ALLIANCE_AND_RESIDUAL_WITH_EXPLICIT_MOVEMENTS_AND_FX"
            if split_ready
            else "LEGACY_COMPOSITION_FAIL_CLOSED"
        ),
    }
