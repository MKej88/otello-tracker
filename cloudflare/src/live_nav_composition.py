from __future__ import annotations

from typing import Any

from estimated_nav_history import _cash_breakdown, _estimated_point
from estimated_nav_history_cash_display import (
    _apply_bemobi_paid_split,
    _apply_bemobi_receivable_split,
    _receivable_state,
)
from estimated_nav_history_display import _split_current_composition
from life360_nav import life360_nav_adjustment


async def _apply_current_bemobi_cash_display(
    repository: Any,
    point: dict[str, Any],
) -> dict[str, Any]:
    """Reuse the history display's explicit Bemobi cash rows for live composition."""
    composition = point.get("composition") or []
    if not isinstance(composition, list):
        return point
    reported_cash = next(
        (item for item in composition if str(item.get("key")) == "reported_cash"),
        None,
    )
    report_date = str((reported_cash or {}).get("details", {}).get("report_date") or "")
    current_date = str(point.get("date") or "")
    if not report_date or not current_date:
        return point

    breakdown = await _cash_breakdown(
        repository,
        start_date=report_date,
        current_date=current_date,
    )
    raw_receivable = await repository.first(
        """
        SELECT associated_receivable_nok, receivable_quality, receivable_components_json
        FROM other_net_assets_daily_estimates
        WHERE estimate_date=?
        LIMIT 1
        """,
        (current_date,),
    )
    receivable = _receivable_state(
        dict(raw_receivable) if raw_receivable is not None else None,
        current_date,
    )

    wrapper = {"current": point}
    wrapper = _apply_bemobi_paid_split(wrapper, breakdown)
    wrapper = _apply_bemobi_receivable_split(wrapper, receivable)
    return wrapper.get("current") or point


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
    if split_ready:
        point = await _apply_current_bemobi_cash_display(repository, point)
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
