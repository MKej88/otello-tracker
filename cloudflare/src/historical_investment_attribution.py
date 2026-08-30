from __future__ import annotations

from decimal import Decimal
from typing import Any

MILLION = Decimal("1000000")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def apply_historical_life360_change_split(
    change: dict[str, Any],
    start_state: dict[str, Any],
    current_state: dict[str, Any],
) -> bool:
    """Attribute historical Life360 market-value change without changing total NAV.

    Before Otello's fair-value reporting policy became active, Life360 lived inside the
    reported residual ONA. This helper makes the investor-facing driver explicit by
    moving the difference between historical Life360 market values from ``other_ona``
    to ``life360``. The sum of drivers is unchanged; this is attribution only.
    """
    if not start_state.get("ready") or not current_state.get("ready"):
        return False

    drivers = change.get("drivers") or []
    if not isinstance(drivers, list):
        return False
    life360 = next((item for item in drivers if item.get("key") == "life360"), None)
    other_ona = next((item for item in drivers if item.get("key") == "other_ona"), None)
    if life360 is None or other_ona is None:
        return False

    share_change = change.get("share_count_change") or {}
    start_shares = int(share_change.get("start_shares") or 0)
    current_shares = int(share_change.get("current_shares") or 0)
    if start_shares <= 0 or current_shares <= 0:
        return False

    reciprocal_scale = (
        Decimal("1") / Decimal(start_shares)
        + Decimal("1") / Decimal(current_shares)
    ) / Decimal("2")

    start_market_nok = _decimal(start_state.get("market_value_nok"))
    current_market_nok = _decimal(current_state.get("market_value_nok"))
    gross_delta_nok = current_market_nok - start_market_nok
    old_life_delta_nok = _decimal(life360.get("amount_mnok")) * MILLION
    reallocation_nok = gross_delta_nok - old_life_delta_nok

    life360["label"] = "Life 360"
    life360["amount_mnok"] = float(gross_delta_nok / MILLION)
    life360["per_share_nok"] = float(gross_delta_nok * reciprocal_scale)
    life360["details"] = {
        **(life360.get("details") or {}),
        "display_available": True,
        "display_basis": "HISTORICAL_MARKET_VALUE_CHANGE_ATTRIBUTION",
        "attribution_only": True,
        "accounting_nav_restatement": False,
        "start_amount_mnok": float(start_market_nok / MILLION),
        "current_amount_mnok": float(current_market_nok / MILLION),
        "start_market_symbol": start_state.get("market_symbol"),
        "current_market_symbol": current_state.get("market_symbol"),
        "start_currency": start_state.get("currency"),
        "current_currency": current_state.get("currency"),
        "start_price": float(_decimal(start_state.get("price"))),
        "current_price": float(_decimal(current_state.get("price"))),
        "start_fx_nok": float(_decimal(start_state.get("fx_rate"))),
        "current_fx_nok": float(_decimal(current_state.get("fx_rate"))),
        "start_holding_quality": start_state.get("holding_quality"),
        "current_holding_quality": current_state.get("holding_quality"),
        "start_method": start_state.get("method"),
        "current_method": current_state.get("method"),
    }

    other_ona_nok = _decimal(other_ona.get("amount_mnok")) * MILLION - reallocation_nok
    other_ona["amount_mnok"] = float(other_ona_nok / MILLION)
    other_ona["per_share_nok"] = float(
        _decimal(other_ona.get("per_share_nok")) - reallocation_nok * reciprocal_scale
    )
    other_ona["details"] = {
        **(other_ona.get("details") or {}),
        "life360_historical_reallocation_mnok": float(reallocation_nok / MILLION),
        "life360_historical_attribution_only": True,
    }

    change["life360_history_split_status"] = {
        "ready": True,
        "policy": "HISTORICAL_MARKET_VALUE_ATTRIBUTION_WITHOUT_NAV_RESTATEMENT",
        "start_date": start_state.get("as_of_date"),
        "current_date": current_state.get("as_of_date"),
        "start_market_symbol": start_state.get("market_symbol"),
        "current_market_symbol": current_state.get("market_symbol"),
        "reallocated_mnok": float(reallocation_nok / MILLION),
    }
    return True
