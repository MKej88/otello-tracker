from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.estimated_nav_history import _cash_breakdown
from app.estimated_nav_history_display import estimated_nav_history as _display_history
from app.option_settlement import MILLION

TOLERANCE_NOK = Decimal("1000")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _component(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("key")) == key), None)


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
            "label": "Bemobi – utbetalt utbytte/JCP",
            "amount_mnok": float(bemobi_paid_nok / MILLION),
            "per_share_nok": float(bemobi_paid_nok / Decimal(shares)),
            "formula": "Netto mottatt Bemobi-utbytte/JCP siden siste rapport",
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


def estimated_nav_history(
    database_path: str | None = None,
    *,
    days: int,
) -> dict[str, Any]:
    result = _display_history(database_path, days=days)
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
    return _apply_bemobi_paid_split(result, breakdown)
