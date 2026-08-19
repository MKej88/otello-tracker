from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

MILLION = Decimal("1000000")


def _object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def settlement_inputs_from_components(components: dict[str, Any]) -> tuple[int, Decimal] | None:
    option = (components.get("other_net_assets") or {}).get("option_liability") or {}
    inputs = option.get("inputs") or {}
    count_raw = inputs.get("option_count")
    strike_raw = inputs.get("strike_nok")
    if strike_raw is None:
        strike_raw = option.get("strike_nok")
    try:
        option_count = int(count_raw)
        strike_nok = Decimal(str(strike_raw))
    except (TypeError, ValueError):
        return None
    if option_count < 0 or strike_nok < 0:
        return None
    return option_count, strike_nok


def settlement_inputs_from_daily_row(row: Any) -> tuple[Decimal, int, Decimal] | None:
    if row is None:
        return None
    inputs = _object(row["option_inputs_json"] if not isinstance(row, dict) else row.get("option_inputs_json"))
    count_raw = inputs.get("option_count")
    strike_raw = row["option_strike_nok"] if not isinstance(row, dict) else row.get("option_strike_nok")
    liability_raw = row["option_liability_nok"] if not isinstance(row, dict) else row.get("option_liability_nok")
    try:
        accounting_liability_nok = Decimal(str(liability_raw or "0"))
        option_count = int(count_raw)
        strike_nok = Decimal(str(strike_raw))
    except (TypeError, ValueError):
        return None
    if accounting_liability_nok < 0 or option_count < 0 or strike_nok < 0:
        return None
    return accounting_liability_nok, option_count, strike_nok


def nav_cash_settlement(
    *,
    pre_option_total_nok: Decimal,
    shares_outstanding: int,
    option_count: int,
    strike_nok: Decimal,
) -> dict[str, Any]:
    """Hypothetical full-realisation cash settlement using NAV as exercise-day price.

    The legal payoff is based on OTEC's closing share price at exercise. For investor NAV,
    this scenario assumes that exercise-day OTEC price equals post-settlement NAV/share.
    The equation is solved self-consistently because paying the cash settlement itself
    reduces NAV.
    """
    if shares_outstanding <= 0 or option_count < 0 or strike_nok < 0:
        raise ValueError("Invalid option settlement inputs")

    shares = Decimal(shares_outstanding)
    options = Decimal(option_count)
    nav_before = pre_option_total_nok / shares

    if option_count == 0 or nav_before <= strike_nok:
        nav_after = nav_before
        settlement_per_option = Decimal("0")
        settlement_nok = Decimal("0")
    else:
        nav_after = (pre_option_total_nok + options * strike_nok) / (shares + options)
        settlement_per_option = max(Decimal("0"), nav_after - strike_nok)
        settlement_nok = options * settlement_per_option

    return {
        "settlement_nok": settlement_nok,
        "settlement_per_option_nok": settlement_per_option,
        "nav_before_option_per_share_nok": nav_before,
        "nav_after_option_per_share_nok": nav_after,
        "economic_total_after_settlement_nok": pre_option_total_nok - settlement_nok,
        "option_count": option_count,
        "strike_nok": strike_nok,
        "in_the_money": settlement_nok > 0,
        "method": "self-consistent-nav-cash-settlement-v1",
        "assumption": (
            "Full Bemobi realisation and return of proceeds; exercise-day OTEC closing price "
            "is assumed equal to post-settlement economic NAV per share."
        ),
    }
