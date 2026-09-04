from __future__ import annotations

from decimal import Decimal
from typing import Any

MILLION = Decimal("1000000")
RECONCILIATION_TOLERANCE_NOK = Decimal("0.01")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _quote_units(state: dict[str, Any]) -> Decimal:
    direct = _decimal(state.get("quote_units"))
    if direct > 0:
        return direct

    shares = _decimal(state.get("shares"))
    units_per_common = _decimal(state.get("quote_units_per_common") or "1")
    if shares > 0 and units_per_common > 0:
        return shares * units_per_common

    price = _decimal(state.get("price"))
    fx_rate = _decimal(state.get("fx_rate"))
    market_value_nok = _decimal(state.get("market_value_nok"))
    if price > 0 and fx_rate > 0 and market_value_nok >= 0:
        return market_value_nok / (price * fx_rate)
    return Decimal("0")


def _period_market_breakdown(
    start_state: dict[str, Any],
    current_state: dict[str, Any],
    *,
    gross_delta_nok: Decimal,
    reciprocal_scale: Decimal,
) -> dict[str, Any]:
    """Return an additive Life360 period split when the listing is comparable.

    Price and FX are only split when both endpoints use the same traded security and
    currency. A holding-change leg is explicit, so the three effects reconcile exactly
    to the total market-value change instead of silently putting share sales into FX.
    """
    start_symbol = str(start_state.get("market_symbol") or "")
    current_symbol = str(current_state.get("market_symbol") or "")
    start_currency = str(start_state.get("currency") or "")
    current_currency = str(current_state.get("currency") or "")
    if (
        not start_symbol
        or start_symbol != current_symbol
        or not start_currency
        or start_currency != current_currency
    ):
        return {
            "period_breakdown_available": False,
            "period_breakdown_reason": "market_listing_or_currency_changed",
        }

    start_units = _quote_units(start_state)
    current_units = _quote_units(current_state)
    start_price = _decimal(start_state.get("price"))
    current_price = _decimal(current_state.get("price"))
    start_fx = _decimal(start_state.get("fx_rate"))
    current_fx = _decimal(current_state.get("fx_rate"))
    if (
        start_units <= 0
        or current_units <= 0
        or start_price <= 0
        or current_price <= 0
        or start_fx <= 0
        or current_fx <= 0
    ):
        return {
            "period_breakdown_available": False,
            "period_breakdown_reason": "invalid_period_market_inputs",
        }

    # Sequential, fully additive decomposition: first price, then FX, then holding.
    price_effect_nok = start_units * (current_price - start_price) * start_fx
    fx_effect_nok = start_units * current_price * (current_fx - start_fx)
    holding_effect_nok = (current_units - start_units) * current_price * current_fx
    residual_nok = gross_delta_nok - (
        price_effect_nok + fx_effect_nok + holding_effect_nok
    )
    if abs(residual_nok) > RECONCILIATION_TOLERANCE_NOK:
        # Source market values are authoritative. Keep the displayed legs exactly
        # reconciled even if upstream decimals were rounded independently.
        holding_effect_nok += residual_nok

    return {
        "period_breakdown_available": True,
        "period_breakdown_method": "PRICE_THEN_FX_THEN_HOLDING_EXACT",
        "attribution_currency": start_currency,
        "start_price": float(start_price),
        "current_price": float(current_price),
        "start_fx_nok": float(start_fx),
        "current_fx_nok": float(current_fx),
        "start_holder_shares": int(start_state.get("shares") or 0),
        "current_holder_shares": int(current_state.get("shares") or 0),
        "price_effect_mnok": float(price_effect_nok / MILLION),
        "price_effect_per_share_nok": float(price_effect_nok * reciprocal_scale),
        "fx_effect_mnok": float(fx_effect_nok / MILLION),
        "fx_effect_per_share_nok": float(fx_effect_nok * reciprocal_scale),
        "holding_effect_mnok": float(holding_effect_nok / MILLION),
        "holding_effect_per_share_nok": float(holding_effect_nok * reciprocal_scale),
        "period_breakdown_residual_nok": float(
            gross_delta_nok - price_effect_nok - fx_effect_nok - holding_effect_nok
        ),
    }


def apply_historical_life360_change_split(
    change: dict[str, Any],
    start_state: dict[str, Any],
    current_state: dict[str, Any],
) -> bool:
    """Attribute Life360 market-value change without changing total NAV.

    The source-backed market values can be used for every investor period. For older
    periods Life360 lived inside residual ONA and is reallocated out for presentation;
    for newer periods the reallocation is normally zero. Either way the total bridge
    remains unchanged.
    """
    if not start_state.get("ready") or not current_state.get("ready"):
        return False

    drivers = change.get("drivers") or []
    if not isinstance(drivers, list):
        return False
    life360 = next((item for item in drivers if item.get("key") == "life360"), None)
    other_ona = next((item for item in drivers if item.get("key") == "other_ona"), None)
    if life360 is None:
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
    if other_ona is None and abs(reallocation_nok) > RECONCILIATION_TOLERANCE_NOK:
        return False

    details = {
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
        "start_holder_shares": int(start_state.get("shares") or 0),
        "current_holder_shares": int(current_state.get("shares") or 0),
        "start_holding_quality": start_state.get("holding_quality"),
        "current_holding_quality": current_state.get("holding_quality"),
        "start_method": start_state.get("method"),
        "current_method": current_state.get("method"),
    }
    details.update(
        _period_market_breakdown(
            start_state,
            current_state,
            gross_delta_nok=gross_delta_nok,
            reciprocal_scale=reciprocal_scale,
        )
    )

    # Never retain a price/FX split from another attribution basis when the endpoints
    # are not comparable (notably 360.AX/AUD -> LIF/USD in the 3Y window).
    if not details.get("period_breakdown_available"):
        for key in (
            "price_effect_mnok",
            "price_effect_per_share_nok",
            "fx_effect_mnok",
            "fx_effect_per_share_nok",
            "holding_effect_mnok",
            "holding_effect_per_share_nok",
        ):
            details.pop(key, None)

    life360["label"] = "Life 360"
    life360["amount_mnok"] = float(gross_delta_nok / MILLION)
    life360["per_share_nok"] = float(gross_delta_nok * reciprocal_scale)
    life360["details"] = details

    if other_ona is not None:
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
        "policy": "PERIOD_MARKET_VALUE_ATTRIBUTION_WITHOUT_NAV_RESTATEMENT",
        "start_date": start_state.get("as_of_date"),
        "current_date": current_state.get("as_of_date"),
        "start_market_symbol": start_state.get("market_symbol"),
        "current_market_symbol": current_state.get("market_symbol"),
        "breakdown_available": bool(details.get("period_breakdown_available")),
        "reallocated_mnok": float(reallocation_nok / MILLION),
    }
    return True
