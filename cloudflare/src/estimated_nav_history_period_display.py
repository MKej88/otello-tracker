from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from economic_nav import _latest_cost_anchors, _nearest_fx
from estimated_nav_history_cash_display import estimated_nav_history as _cash_display_history
from option_settlement import MILLION


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _apply_period_operating_cost_split(
    result: dict[str, Any],
    period_cost_nok: Decimal,
    *,
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Replace reset-sensitive cost deltas with expense accrued over the selected period."""
    change = result.get("change") or {}
    drivers = change.get("drivers") or []
    if not change.get("ready") or not isinstance(drivers, list):
        return result

    other_cash = next(
        (item for item in drivers if str(item.get("key")) == "other_cash"),
        None,
    )
    if other_cash is None or other_cash.get("amount_mnok") is None:
        return result

    total_other_cash_nok = _decimal(other_cash.get("amount_mnok")) * MILLION
    operating_effect_nok = -abs(_decimal(period_cost_nok))
    remaining_cash_nok = total_other_cash_nok - operating_effect_nok
    old_details = dict(other_cash.get("details") or {})
    other_cash["details"] = {
        **old_details,
        "legacy_operating_cost_mnok": old_details.get("operating_cost_mnok"),
        "legacy_other_movements_mnok": old_details.get("other_movements_mnok"),
        "operating_cost_mnok": float(operating_effect_nok / MILLION),
        "other_movements_mnok": float(remaining_cash_nok / MILLION),
        "operating_cost_period_method": "SEGMENTED_ACCRUAL_ACROSS_REPORTED_CASH_ANCHORS",
        "operating_cost_segments": segments or [],
    }
    change["period_operating_cost_status"] = {
        "ready": True,
        "effect_mnok": float(operating_effect_nok / MILLION),
        "segment_count": len(segments or []),
    }
    return result


async def _period_operating_cost(
    repository,
    *,
    start_date: str,
    current_date: str,
) -> dict[str, Any]:
    start = date.fromisoformat(start_date)
    current = date.fromisoformat(current_date)
    if current <= start:
        return {"ready": True, "cost_nok": Decimal("0"), "segments": []}

    rows = await repository.all(
        """
        SELECT DISTINCT as_of_date
        FROM cash_anchors
        WHERE anchor_type='REPORTED' AND as_of_date > ? AND as_of_date <= ?
        ORDER BY as_of_date
        """,
        (start_date, current_date),
    )
    boundaries = [
        date.fromisoformat(str(row.get("as_of_date")))
        for row in rows
        if row.get("as_of_date")
    ]

    cursor = start
    total = Decimal("0")
    segments: list[dict[str, Any]] = []
    endpoints = boundaries + [current]
    for endpoint in endpoints:
        if endpoint <= cursor:
            cursor = max(cursor, endpoint)
            continue

        is_report_boundary = endpoint in boundaries
        reference = endpoint - timedelta(days=1) if is_report_boundary else endpoint
        days_in_segment = (endpoint - cursor).days
        cost_anchor = (await _latest_cost_anchors(repository, reference.isoformat())).get("BASE")
        fx = await _nearest_fx(repository, "USD", reference.isoformat())
        if cost_anchor is None or fx is None:
            return {
                "ready": False,
                "reason": "missing_period_operating_cost_inputs",
                "segment_start": cursor.isoformat(),
                "segment_end": endpoint.isoformat(),
                "reference_date": reference.isoformat(),
            }

        daily_usd = _decimal(cost_anchor["amount_usd_decimal"]) / Decimal(
            int(cost_anchor["period_days_int"])
        )
        usd_nok = _decimal(fx.get("rate"))
        segment_cost_nok = daily_usd * Decimal(days_in_segment) * usd_nok
        total += segment_cost_nok
        segments.append(
            {
                "start_date": cursor.isoformat(),
                "end_date": endpoint.isoformat(),
                "days": days_in_segment,
                "reference_date": reference.isoformat(),
                "cost_anchor_effective_from": cost_anchor.get("effective_from"),
                "cost_anchor_source_document_id": cost_anchor.get("source_document_id"),
                "daily_cost_usd": float(daily_usd),
                "usd_nok": float(usd_nok),
                "usd_nok_date": fx.get("rate_date"),
                "cost_mnok": float(segment_cost_nok / MILLION),
            }
        )
        cursor = endpoint

    return {"ready": True, "cost_nok": total, "segments": segments}


async def estimated_nav_history(repository, *, days: int) -> dict[str, Any]:
    result = await _cash_display_history(repository, days=days)
    if not result.get("ready"):
        return result

    change = result.get("change") or {}
    if not change.get("ready"):
        return result
    start_date = str(change.get("resolved_start") or "")
    current_date = str(change.get("current_date") or result.get("to") or "")
    if not start_date or not current_date:
        return result

    period_cost = await _period_operating_cost(
        repository,
        start_date=start_date,
        current_date=current_date,
    )
    if not period_cost.get("ready"):
        change["period_operating_cost_status"] = period_cost
        return result

    return _apply_period_operating_cost_split(
        result,
        _decimal(period_cost.get("cost_nok")),
        segments=period_cost.get("segments") or [],
    )
