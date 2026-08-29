from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from estimated_nav_history import _cash_breakdown
from estimated_nav_history_display import estimated_nav_history as _display_history
from option_settlement import MILLION

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


async def estimated_nav_history(repository, *, days: int) -> dict[str, Any]:
    result = await _display_history(repository, days=days)
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
    receivable = _receivable_state(raw_receivable, current_date)

    result = _apply_bemobi_paid_split(result, breakdown)
    return _apply_bemobi_receivable_split(result, receivable)
