from __future__ import annotations

from decimal import Decimal
from typing import Any

from app import estimated_nav_history_cash_display_base as _base
from app.db.connection import get_connection

# Preserve the existing module surface, including private helpers used by tests.
for _name in dir(_base):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_base, _name)

_base_estimated_nav_history = _base.estimated_nav_history
_MILLION = Decimal("1000000")
_PATENT_TOLERANCE_NOK = Decimal("1000")


def _period_patent_proceeds(
    connection,
    *,
    start_date: str,
    current_date: str,
) -> dict[str, Any]:
    """Return confirmed patent proceeds inside the exact NAV attribution window."""
    rows = connection.execute(
        """
        SELECT movement_date, amount_nok, amount_original, currency, description,
               external_movement_id, source_document_id
        FROM cash_movements
        WHERE movement_date > ? AND movement_date <= ?
          AND identified_type='PATENT_PROCEEDS'
          AND confidence='CONFIRMED'
        ORDER BY movement_date, id
        """,
        (start_date, current_date),
    ).fetchall()
    events = [dict(row) for row in rows]
    amount_nok = sum(
        (Decimal(str(row.get("amount_nok") or "0")) for row in events),
        Decimal("0"),
    )
    return {"ready": True, "amount_nok": amount_nok, "events": events}


def _apply_period_patent_split(
    result: dict[str, Any],
    patent_nok: Decimal,
    *,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reclassify confirmed patent cash out of the residual without changing NAV."""
    change = result.get("change") or {}
    drivers = change.get("drivers") or []
    event_list = events or []
    if not change.get("ready") or not isinstance(drivers, list):
        return result
    if any(str(item.get("key")) == "patent_proceeds" for item in drivers):
        return result
    if abs(patent_nok) <= _PATENT_TOLERANCE_NOK:
        change["period_patent_status"] = {
            "ready": True,
            "effect_mnok": 0.0,
            "event_count": len(event_list),
        }
        return result

    other_cash = next(
        (item for item in drivers if str(item.get("key")) == "other_cash"),
        None,
    )
    share_change = change.get("share_count_change") or {}
    start_shares = int(share_change.get("start_shares") or 0)
    current_shares = int(share_change.get("current_shares") or 0)
    if other_cash is None or start_shares <= 0 or current_shares <= 0:
        change["period_patent_status"] = {
            "ready": False,
            "reason": "missing_other_cash_or_share_count",
            "event_count": len(event_list),
        }
        return result

    reciprocal_scale = (
        Decimal("1") / Decimal(start_shares)
        + Decimal("1") / Decimal(current_shares)
    ) / Decimal("2")
    patent_per_share = patent_nok * reciprocal_scale
    original_amount_nok = Decimal(str(other_cash.get("amount_mnok") or "0")) * _MILLION
    original_per_share = Decimal(str(other_cash.get("per_share_nok") or "0"))

    other_cash["amount_mnok"] = float((original_amount_nok - patent_nok) / _MILLION)
    other_cash["per_share_nok"] = float(original_per_share - patent_per_share)
    details = dict(other_cash.get("details") or {})
    residual_mnok = details.get("other_movements_mnok")
    if residual_mnok is not None:
        details["other_movements_mnok"] = float(
            (Decimal(str(residual_mnok)) * _MILLION - patent_nok) / _MILLION
        )
    details["patent_proceeds_split_mnok"] = float(patent_nok / _MILLION)
    other_cash["details"] = details

    drivers.append(
        {
            "key": "patent_proceeds",
            "label": "Patentoppgjør",
            "amount_mnok": float(patent_nok / _MILLION),
            "per_share_nok": float(patent_per_share),
            "impact_kind": "TOTAL_AND_PER_SHARE",
            "details": {
                "events": event_list,
                "display_policy": "EXPLICIT_CONFIRMED_CASH_MOVEMENT",
            },
        }
    )
    change["period_patent_status"] = {
        "ready": True,
        "effect_mnok": float(patent_nok / _MILLION),
        "effect_per_share_nok": float(patent_per_share),
        "event_count": len(event_list),
    }
    return result


def estimated_nav_history(
    database_path: str | None = None,
    *,
    days: int,
    year_to_date: bool = False,
) -> dict[str, Any]:
    result = _base_estimated_nav_history(
        database_path,
        days=days,
        year_to_date=year_to_date,
    )
    change = result.get("change") or {}
    if not result.get("ready") or not change.get("ready"):
        return result

    start_date = str(change.get("resolved_start") or "")
    current_date = str(change.get("current_date") or result.get("to") or "")
    if not start_date or not current_date:
        return result

    with get_connection(database_path) as connection:
        patent = _period_patent_proceeds(
            connection,
            start_date=start_date,
            current_date=current_date,
        )
    return _apply_period_patent_split(
        result,
        Decimal(str(patent.get("amount_nok") or "0")),
        events=patent.get("events") or [],
    )
