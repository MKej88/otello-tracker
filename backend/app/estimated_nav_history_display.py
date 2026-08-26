from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from app.estimated_nav_history import estimated_nav_history as _estimated_nav_history
from app.life360_nav import life360_nav_adjustment
from app.option_settlement import MILLION

TOLERANCE_NOK = Decimal("1000")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _item(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("key")) == key), None)


def _state_details(state: dict[str, Any]) -> dict[str, Any]:
    ready = bool(state.get("ready"))
    return {
        "active": ready,
        "display_available": ready,
        "reason": state.get("reason"),
        "shares": state.get("shares"),
        "price_usd": None if state.get("price") is None else float(_decimal(state.get("price"))),
        "price_date": state.get("price_date"),
        "price_source": state.get("price_source"),
        "fx_usd_nok": None if state.get("fx_rate") is None else float(_decimal(state.get("fx_rate"))),
        "fx_date": state.get("fx_date"),
        "anchor_date": state.get("anchor_date"),
        "anchor_price_usd": None if state.get("anchor_price_usd") is None else float(_decimal(state.get("anchor_price_usd"))),
        "anchor_price_date": state.get("anchor_price_date"),
        "market_value_mnok": None if not ready else float(_decimal(state.get("market_value_nok")) / MILLION),
        "embedded_value_mnok": None if not ready else float(_decimal(state.get("embedded_value_nok")) / MILLION),
        "adjustment_mnok": None if not ready else float(_decimal(state.get("adjustment_nok")) / MILLION),
        "display_basis": "GROSS_MARKET_VALUE_EX_OONA" if ready else "UNAVAILABLE",
    }


def _enrich_current(point: dict[str, Any], state: dict[str, Any]) -> None:
    composition = point.get("composition") or []
    if not isinstance(composition, list):
        return
    life360 = _item(composition, "life360")
    ona = _item(composition, "ona")
    if life360 is None or ona is None:
        return

    details = _state_details(state)
    life360["details"] = {**(life360.get("details") or {}), **details}
    if not state.get("ready"):
        life360["formula"] = "Life360-verdi er ikke tilgjengelig med gyldig markeds- og rapportgrunnlag"
        return

    market_nok = _decimal(state.get("market_value_nok"))
    embedded_nok = _decimal(state.get("embedded_value_nok"))
    adjustment_nok = _decimal(state.get("adjustment_nok"))
    old_life360_nok = _decimal(life360.get("amount_mnok")) * MILLION
    if abs(old_life360_nok - adjustment_nok) > TOLERANCE_NOK:
        life360["details"] = {
            **life360["details"],
            "active": False,
            "display_available": False,
            "reason": "life360_adjustment_does_not_reconcile",
        }
        return

    shares = int(point.get("shares_outstanding") or 0)
    if shares <= 0:
        life360["details"] = {
            **life360["details"],
            "active": False,
            "display_available": False,
            "reason": "invalid_share_count",
        }
        return

    old_ona_nok = _decimal(ona.get("amount_mnok")) * MILLION
    ona_nok = old_ona_nok - embedded_nok
    ona["amount_mnok"] = float(ona_nok / MILLION)
    ona["per_share_nok"] = float(ona_nok / Decimal(shares))
    ona["formula"] = (
        "Regnskapsmessig ONA + regnskapsført opsjonsforpliktelse − "
        "Life360-verdi innebygd i siste rapporterte ONA"
    )
    ona["details"] = {
        **(ona.get("details") or {}),
        "life360_embedded_removed_mnok": float(embedded_nok / MILLION),
        "life360_anchor_date": state.get("anchor_date"),
    }

    life360["amount_mnok"] = float(market_nok / MILLION)
    life360["per_share_nok"] = float(market_nok / Decimal(shares))
    life360["formula"] = "37 028 LIF-aksjer × siste LIF-kurs × USD/NOK"


def _enrich_change(
    change: dict[str, Any],
    start_state: dict[str, Any],
    current_state: dict[str, Any],
) -> None:
    drivers = change.get("drivers") or []
    if not isinstance(drivers, list):
        return
    life360 = _item(drivers, "life360")
    other_ona = _item(drivers, "other_ona")
    if life360 is None:
        return

    both_ready = bool(start_state.get("ready") and current_state.get("ready"))
    life360["details"] = {
        **(life360.get("details") or {}),
        "display_available": both_ready,
        "start_active": bool(start_state.get("ready")),
        "current_active": bool(current_state.get("ready")),
        "start_reason": start_state.get("reason"),
        "current_reason": current_state.get("reason"),
        "start_market_value_mnok": None if not start_state.get("ready") else float(_decimal(start_state.get("market_value_nok")) / MILLION),
        "current_market_value_mnok": None if not current_state.get("ready") else float(_decimal(current_state.get("market_value_nok")) / MILLION),
        "start_embedded_value_mnok": None if not start_state.get("ready") else float(_decimal(start_state.get("embedded_value_nok")) / MILLION),
        "current_embedded_value_mnok": None if not current_state.get("ready") else float(_decimal(current_state.get("embedded_value_nok")) / MILLION),
    }
    if not both_ready:
        return

    old_life_delta_nok = _decimal(life360.get("amount_mnok")) * MILLION
    start_market_nok = _decimal(start_state.get("market_value_nok"))
    current_market_nok = _decimal(current_state.get("market_value_nok"))
    gross_delta_nok = current_market_nok - start_market_nok
    reallocation_nok = gross_delta_nok - old_life_delta_nok

    share_change = change.get("share_count_change") or {}
    start_shares = int(share_change.get("start_shares") or 0)
    current_shares = int(share_change.get("current_shares") or 0)
    if start_shares <= 0 or current_shares <= 0:
        life360["details"] = {
            **life360["details"],
            "display_available": False,
            "reason": "invalid_share_count",
        }
        return
    reciprocal_scale = (
        Decimal("1") / Decimal(start_shares)
        + Decimal("1") / Decimal(current_shares)
    ) / Decimal("2")

    life360["amount_mnok"] = float(gross_delta_nok / MILLION)
    life360["per_share_nok"] = float(gross_delta_nok * reciprocal_scale)
    life360["details"] = {
        **life360["details"],
        "start_amount_mnok": float(start_market_nok / MILLION),
        "current_amount_mnok": float(current_market_nok / MILLION),
        "display_basis": "GROSS_MARKET_VALUE_CHANGE",
    }

    if other_ona is not None:
        other_ona_nok = _decimal(other_ona.get("amount_mnok")) * MILLION - reallocation_nok
        other_ona["amount_mnok"] = float(other_ona_nok / MILLION)
        other_ona["per_share_nok"] = float(
            _decimal(other_ona.get("per_share_nok")) - reallocation_nok * reciprocal_scale
        )
        other_ona["details"] = {
            **(other_ona.get("details") or {}),
            "life360_embedded_reallocation_mnok": float(reallocation_nok / MILLION),
        }


def estimated_nav_history(database_path: str | None = None, *, days: int) -> dict[str, Any]:
    """Reference-model equivalent of the Worker gross Life360 presentation."""
    result = deepcopy(_estimated_nav_history(database_path, days=days))
    if not result.get("ready"):
        return result

    current = result.get("current") or {}
    current_date = str(current.get("date") or result.get("to") or "")
    current_state = (
        life360_nav_adjustment(as_of_date=current_date, database_path=database_path)
        if current_date
        else {"ready": False, "reason": "missing_current_date"}
    )
    if current:
        _enrich_current(current, current_state)

    change = result.get("change") or {}
    if change.get("ready"):
        start_date = str(change.get("resolved_start") or "")
        end_date = str(change.get("current_date") or current_date)
        start_state = (
            life360_nav_adjustment(as_of_date=start_date, database_path=database_path)
            if start_date
            else {"ready": False, "reason": "missing_start_date"}
        )
        end_state = current_state if end_date == current_date else (
            life360_nav_adjustment(as_of_date=end_date, database_path=database_path)
            if end_date
            else {"ready": False, "reason": "missing_current_date"}
        )
        _enrich_change(change, start_state, end_state)

    result["life360_display_policy"] = "GROSS_MARKET_VALUE_EX_EMBEDDED_ONA"
    return result
