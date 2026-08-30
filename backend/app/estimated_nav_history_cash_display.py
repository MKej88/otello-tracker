from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.economic_nav import _latest_cost_anchors, _nearest_fx
from app.estimated_nav_history import _cash_breakdown
from app.estimated_nav_history_display import estimated_nav_history as _display_history
from app.option_settlement import MILLION

TOLERANCE_NOK = Decimal("1000")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _component(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("key")) == key), None)


def _receivable_state(row: dict[str, Any] | None, current_date: str) -> dict[str, Any]:
    if row is None:
        return {"ready": False, "reason": "missing_bemobi_receivable", "date": current_date}
    try:
        components = json.loads(str(row.get("receivable_components_json") or "[]"))
    except (TypeError, json.JSONDecodeError):
        components = []
    if not isinstance(components, list):
        components = []
    return {
        "ready": True,
        "date": current_date,
        "amount_nok": _decimal(row.get("associated_receivable_nok")),
        "quality": row.get("receivable_quality"),
        "components": components,
    }


def _apply_period_operating_cost_split(
    result: dict[str, Any],
    period_cost_nok: Decimal,
    *,
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use period expense instead of the reset-sensitive difference between two cash anchors."""
    change = result.get("change") or {}
    drivers = change.get("drivers") or []
    if not change.get("ready") or not isinstance(drivers, list):
        return result
    other_cash = next((item for item in drivers if str(item.get("key")) == "other_cash"), None)
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


def _period_operating_cost(
    connection,
    *,
    start_date: str,
    current_date: str,
) -> dict[str, Any]:
    """Accrue operating expense over the selected period, splitting at report cash anchors."""
    start = date.fromisoformat(start_date)
    current = date.fromisoformat(current_date)
    if current <= start:
        return {"ready": True, "cost_nok": Decimal("0"), "segments": []}

    rows = connection.execute(
        """
        SELECT DISTINCT as_of_date
        FROM cash_anchors
        WHERE anchor_type='REPORTED' AND as_of_date > ? AND as_of_date <= ?
        ORDER BY as_of_date
        """,
        (start_date, current_date),
    ).fetchall()
    boundaries = [
        date.fromisoformat(str(row["as_of_date"]))
        for row in rows
        if row["as_of_date"]
    ]

    cursor = start
    total = Decimal("0")
    segments: list[dict[str, Any]] = []
    for endpoint in boundaries + [current]:
        if endpoint <= cursor:
            continue
        is_report_boundary = endpoint in boundaries
        reference = endpoint - timedelta(days=1) if is_report_boundary else endpoint
        days_in_segment = (endpoint - cursor).days
        cost_anchor = _latest_cost_anchors(connection, reference.isoformat()).get("BASE")
        fx = _nearest_fx(connection, "USD", reference.isoformat())
        if cost_anchor is None or fx is None:
            return {
                "ready": False,
                "reason": "missing_period_operating_cost_inputs",
                "segment_start": cursor.isoformat(),
                "segment_end": endpoint.isoformat(),
                "reference_date": reference.isoformat(),
            }

        daily_usd = _decimal(cost_anchor["amount_usd_decimal"]) / Decimal(int(cost_anchor["period_days_int"]))
        usd_nok = _decimal(fx["rate"])
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
                "usd_nok_date": fx["rate_date"],
                "cost_mnok": float(segment_cost_nok / MILLION),
            }
        )
        cursor = endpoint

    return {"ready": True, "cost_nok": total, "segments": segments}


def _apply_bemobi_paid_split(
    result: dict[str, Any],
    cash_breakdown: dict[str, Any],
) -> dict[str, Any]:
    """Split paid Bemobi distributions out of other post-report cash movements."""
    current = result.get("current") or {}
    composition = current.get("composition") or []
    if not isinstance(composition, list):
        return result
    if _component(composition, "bemobi_paid_since_report") is not None:
        return result
    if not cash_breakdown.get("ready"):
        return result

    bemobi_paid_nok = _decimal(cash_breakdown.get("bemobi_net_cash_nok"))
    if abs(bemobi_paid_nok) <= TOLERANCE_NOK:
        return result

    other_cash = _component(composition, "other_cash_since_report")
    shares = int(current.get("shares_outstanding") or 0)
    if other_cash is None or shares <= 0:
        current["bemobi_paid_cash_split_status"] = {
            "ready": False,
            "reason": "missing_other_cash_or_share_count",
        }
        return result

    old_total_nok = sum(
        (_decimal(item.get("amount_mnok")) * MILLION for item in composition),
        Decimal("0"),
    )
    other_cash_nok = _decimal(other_cash.get("amount_mnok")) * MILLION
    residual_cash_nok = other_cash_nok - bemobi_paid_nok

    new_components = [
        dict(item)
        for item in composition
        if str(item.get("key")) != "other_cash_since_report"
    ]
    if abs(residual_cash_nok) > TOLERANCE_NOK:
        residual = dict(other_cash)
        residual["amount_mnok"] = float(residual_cash_nok / MILLION)
        residual["per_share_nok"] = float(residual_cash_nok / Decimal(shares))
        residual["details"] = {
            **(residual.get("details") or {}),
            "bemobi_paid_split_mnok": float(bemobi_paid_nok / MILLION),
        }
        new_components.append(residual)

    gross_nok = _decimal(cash_breakdown.get("bemobi_gross_cash_nok"))
    withholding_nok = _decimal(cash_breakdown.get("bemobi_withholding_nok"))
    new_components.append(
        {
            "key": "bemobi_paid_since_report",
            "label": "Bekreftede øvrige kontantbevegelser",
            "amount_mnok": float(bemobi_paid_nok / MILLION),
            "per_share_nok": float(bemobi_paid_nok / Decimal(shares)),
            "formula": "Utbetalt utbytte/renter fra Bemobi siden siste rapport",
            "details": {
                "gross_mnok": float(gross_nok / MILLION),
                "withholding_mnok": float(withholding_nok / MILLION),
                "net_mnok": float(bemobi_paid_nok / MILLION),
                "receipt_rows": int(cash_breakdown.get("bemobi_receipt_rows") or 0),
                "withholding_rows": int(cash_breakdown.get("withholding_rows") or 0),
                "display_policy": "EXPLICIT_POST_REPORT_CASH_MOVEMENT",
            },
        }
    )

    new_total_nok = sum(
        (_decimal(item.get("amount_mnok")) * MILLION for item in new_components),
        Decimal("0"),
    )
    if abs(old_total_nok - new_total_nok) > TOLERANCE_NOK:
        current["bemobi_paid_cash_split_status"] = {
            "ready": False,
            "reason": "bemobi_paid_split_does_not_reconcile",
            "residual_nok": float(old_total_nok - new_total_nok),
        }
        return result

    current["composition"] = new_components
    current["bemobi_paid_cash_split_status"] = {
        "ready": True,
        "gross_mnok": float(gross_nok / MILLION),
        "withholding_mnok": float(withholding_nok / MILLION),
        "net_mnok": float(bemobi_paid_nok / MILLION),
    }
    return result


def _apply_bemobi_receivable_split(
    result: dict[str, Any],
    receivable: dict[str, Any],
) -> dict[str, Any]:
    """Show unpaid Bemobi distributions explicitly without changing total NAV."""
    current = result.get("current") or {}
    composition = current.get("composition") or []
    if not isinstance(composition, list):
        return result
    if _component(composition, "bemobi_receivable") is not None:
        return result
    if not receivable.get("ready"):
        return result

    receivable_nok = _decimal(receivable.get("amount_nok"))
    if abs(receivable_nok) <= TOLERANCE_NOK:
        return result

    shares = int(current.get("shares_outstanding") or 0)
    if shares <= 0:
        current["bemobi_receivable_split_status"] = {
            "ready": False,
            "reason": "invalid_share_count",
        }
        return result

    old_total_nok = sum(
        (_decimal(item.get("amount_mnok")) * MILLION for item in composition),
        Decimal("0"),
    )
    fx = _component(composition, "fx_since_report")
    fx_nok = _decimal((fx or {}).get("amount_mnok")) * MILLION
    residual_fx_nok = fx_nok - receivable_nok

    components_raw = receivable.get("components")
    components = components_raw if isinstance(components_raw, list) else []
    ex_dates = sorted({str(item.get("ex_date")) for item in components if item.get("ex_date")})
    payment_dates = sorted(
        {str(item.get("payment_date")) for item in components if item.get("payment_date")}
    )
    receivable_component = {
        "key": "bemobi_receivable",
        "label": "Bemobi – tilgode utbytte/renter",
        "amount_mnok": float(receivable_nok / MILLION),
        "per_share_nok": float(receivable_nok / Decimal(shares)),
        "formula": "Opptjent Bemobi-utbytte/renter fra ex-dato til betalingsdato",
        "details": {
            "quality": receivable.get("quality"),
            "ex_dates": ex_dates,
            "payment_dates": payment_dates,
            "components": components,
            "display_policy": "EXPLICIT_RECEIVABLE_FROM_EX_DATE_UNTIL_PAYMENT",
        },
    }

    new_components: list[dict[str, Any]] = []
    receivable_inserted = False
    fx_seen = False
    for item in composition:
        key = str(item.get("key"))
        if key == "fx_since_report":
            fx_seen = True
            if abs(residual_fx_nok) > TOLERANCE_NOK:
                adjusted = dict(item)
                adjusted["amount_mnok"] = float(residual_fx_nok / MILLION)
                adjusted["per_share_nok"] = float(residual_fx_nok / Decimal(shares))
                adjusted["details"] = {
                    **(adjusted.get("details") or {}),
                    "bemobi_receivable_split_mnok": float(receivable_nok / MILLION),
                }
                new_components.append(adjusted)
            continue
        new_components.append(dict(item))
        if key == "reported_cash" and not receivable_inserted:
            new_components.append(receivable_component)
            receivable_inserted = True

    if not receivable_inserted:
        new_components.append(receivable_component)
    if not fx_seen and abs(residual_fx_nok) > TOLERANCE_NOK:
        new_components.append(
            {
                "key": "fx_since_report",
                "label": "Valutaeffekt siden siste rapport",
                "amount_mnok": float(residual_fx_nok / MILLION),
                "per_share_nok": float(residual_fx_nok / Decimal(shares)),
                "formula": "Valutaeffekt siden siste rapport, ekskl. Bemobi-fordring",
                "details": {
                    "bemobi_receivable_split_mnok": float(receivable_nok / MILLION),
                    "display_policy": "RESIDUAL_AFTER_RECEIVABLE_SPLIT",
                },
            }
        )

    new_total_nok = sum(
        (_decimal(item.get("amount_mnok")) * MILLION for item in new_components),
        Decimal("0"),
    )
    if abs(old_total_nok - new_total_nok) > TOLERANCE_NOK:
        current["bemobi_receivable_split_status"] = {
            "ready": False,
            "reason": "bemobi_receivable_split_does_not_reconcile",
            "residual_nok": float(old_total_nok - new_total_nok),
        }
        return result

    current["composition"] = new_components
    current["bemobi_receivable_split_status"] = {
        "ready": True,
        "amount_mnok": float(receivable_nok / MILLION),
        "quality": receivable.get("quality"),
        "ex_dates": ex_dates,
        "payment_dates": payment_dates,
    }
    return result


def estimated_nav_history(
    database_path: str | None = None,
    *,
    days: int,
    year_to_date: bool = False,
) -> dict[str, Any]:
    result = _display_history(
        database_path, days=days, year_to_date=year_to_date
    )
    if not result.get("ready"):
        return result

    current = result.get("current") or {}
    current_date = str(current.get("date") or result.get("to") or "")
    composition = current.get("composition") or []
    reported_cash = (
        _component(composition, "reported_cash")
        if isinstance(composition, list)
        else None
    )
    report_date = str((reported_cash or {}).get("details", {}).get("report_date") or "")
    if not report_date or not current_date:
        return result

    with get_connection(database_path) as connection:
        breakdown = _cash_breakdown(
            connection,
            start_date=report_date,
            current_date=current_date,
        )
        raw_receivable = connection.execute(
            """
            SELECT associated_receivable_nok, receivable_quality, receivable_components_json
            FROM other_net_assets_daily_estimates
            WHERE estimate_date=?
            LIMIT 1
            """,
            (current_date,),
        ).fetchone()
        receivable = _receivable_state(
            dict(raw_receivable) if raw_receivable is not None else None,
            current_date,
        )

        change = result.get("change") or {}
        start_date = str(change.get("resolved_start") or "")
        period_cost = None
        if change.get("ready") and start_date:
            period_cost = _period_operating_cost(
                connection,
                start_date=start_date,
                current_date=current_date,
            )

    if period_cost is not None:
        if period_cost.get("ready"):
            result = _apply_period_operating_cost_split(
                result,
                _decimal(period_cost.get("cost_nok")),
                segments=period_cost.get("segments") or [],
            )
        else:
            (result.get("change") or {})["period_operating_cost_status"] = period_cost

    result = _apply_bemobi_paid_split(result, breakdown)
    return _apply_bemobi_receivable_split(result, receivable)
