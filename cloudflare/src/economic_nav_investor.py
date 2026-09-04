from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from economic_nav import economic_nav_summary as accounting_economic_nav_summary
from life360_nav import life360_nav_adjustment
from live_nav_composition import live_nav_composition
from option_settlement import (
    MILLION,
    nav_cash_settlement,
    settlement_inputs_from_components,
)
from nav_waterfall_attribution import symmetric_two_factor_attribution

FULL_CALCULATION_VERSION = "full-market-nav-daily-v2"
CONSERVATIVE_COST_POLICY = "MAX_BASE_RUN_RATE_AND_SOURCE_CONSERVATIVE"
LIVE_COMPOSITION_TOLERANCE_NOK = Decimal("0.000001")


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _discount_pct(
    otec_price_nok: Decimal | None, nav_per_share_nok: Decimal
) -> float | None:
    if otec_price_nok is None or nav_per_share_nok <= 0:
        return None
    return float((Decimal("1") - otec_price_nok / nav_per_share_nok) * Decimal("100"))


def _components(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _life360_public(raw: dict[str, Any]) -> dict[str, Any]:
    result = dict(raw)
    for key in (
        "price",
        "fx_rate",
        "anchor_price_usd",
        "market_value_usd",
        "market_value_nok",
        "embedded_value_usd",
        "embedded_value_nok",
        "adjustment_nok",
    ):
        value = result.get(key)
        if isinstance(value, Decimal):
            result[key] = float(value)
    adjustment = Decimal(str(raw.get("adjustment_nok") or "0"))
    result["adjustment_mnok"] = _float(adjustment / MILLION)
    if raw.get("market_value_nok") is not None:
        result["market_value_mnok"] = _float(
            Decimal(str(raw["market_value_nok"])) / MILLION
        )
    if raw.get("embedded_value_nok") is not None:
        result["embedded_value_mnok"] = _float(
            Decimal(str(raw["embedded_value_nok"])) / MILLION
        )
    return result


def _life360_month_price_effect(
    start: dict[str, Any],
    current: dict[str, Any],
    start_shares_outstanding: int,
    current_shares_outstanding: int,
) -> float | None:
    """Returner ren LIF-kurseffekt per OTEC-aksje, uten USD/NOK-effekten."""
    if (
        not start.get("ready")
        or not current.get("ready")
        or start_shares_outstanding <= 0
        or current_shares_outstanding <= 0
    ):
        return None
    try:
        start_holding = int(start.get("shares") or 0)
        current_holding = int(current.get("shares") or 0)
        start_price = Decimal(str(start["price"]))
        current_price = Decimal(str(current["price"]))
        start_fx = Decimal(str(start["fx_rate"]))
        current_fx = Decimal(str(current["fx_rate"]))
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return None
    if start_holding <= 0 or start_holding != current_holding:
        return None
    if not all(
        value.is_finite() and value > 0
        for value in (start_price, current_price, start_fx, current_fx)
    ):
        return None
    attribution = symmetric_two_factor_attribution(
        shares=current_holding,
        anchor_price=start_price,
        current_price=current_price,
        anchor_fx=start_fx,
        current_fx=current_fx,
    )
    reciprocal_scale = (
        Decimal("1") / Decimal(start_shares_outstanding)
        + Decimal("1") / Decimal(current_shares_outstanding)
    ) / Decimal("2")
    return float(attribution["price_effect_nok"] * reciprocal_scale)


def _apply_conservative_cost_floor(
    operating: dict[str, Any],
) -> tuple[Decimal, Decimal, dict[str, Any]]:
    """A conservative scenario may never assume lower operating cost than BASE."""
    base_cost_nok = Decimal(str(operating.get("base_mnok") or "0")) * MILLION
    source_conservative_cost_nok = (
        Decimal(str(operating.get("conservative_mnok") or "0")) * MILLION
    )
    conservative_cost_nok = max(base_cost_nok, source_conservative_cost_nok)

    public_operating = dict(operating)
    public_operating["conservative_source_mnok"] = _float(
        source_conservative_cost_nok / MILLION
    )
    public_operating["conservative_mnok"] = _float(conservative_cost_nok / MILLION)
    public_operating["conservative_floor_applied"] = (
        source_conservative_cost_nok < base_cost_nok
    )
    public_operating["conservative_policy"] = CONSERVATIVE_COST_POLICY

    base_annualized = operating.get("base_annualized_usd_m")
    source_conservative_annualized = operating.get("conservative_annualized_usd_m")
    if source_conservative_annualized is not None:
        public_operating["conservative_source_annualized_usd_m"] = (
            source_conservative_annualized
        )
    if base_annualized is not None and source_conservative_annualized is not None:
        public_operating["conservative_annualized_usd_m"] = max(
            float(base_annualized), float(source_conservative_annualized)
        )

    return base_cost_nok, conservative_cost_nok, public_operating


async def economic_nav_summary(repository) -> dict[str, Any]:
    base = await accounting_economic_nav_summary(repository)
    if not base.get("ready"):
        return base

    as_of_date = str(base.get("as_of_date") or "")
    row = await repository.first(
        """
        SELECT as_of_at, created_at, updated_at, nav_total_nok, nav_per_share_nok,
               otec_price_nok, shares_outstanding, components_json
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='FULL'
          AND substr(as_of_at,1,10)=?
        ORDER BY as_of_at DESC, id DESC LIMIT 1
        """,
        (FULL_CALCULATION_VERSION, as_of_date),
    )
    month_target = (date.fromisoformat(as_of_date) - timedelta(days=30)).isoformat()
    month_row = await repository.first(
        """
        SELECT substr(as_of_at, 1, 10) AS as_of_date, shares_outstanding
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='FULL'
          AND substr(as_of_at, 1, 10) <= ?
        ORDER BY as_of_at DESC, id DESC LIMIT 1
        """,
        (FULL_CALCULATION_VERSION, month_target),
    )
    if row is None:
        return {"ready": False, "reason": "missing_full_nav_row"}

    settlement_inputs = settlement_inputs_from_components(
        _components(row.get("components_json"))
    )
    if settlement_inputs is None:
        return {
            "ready": False,
            "reason": "missing_option_settlement_inputs",
            "as_of_date": as_of_date,
        }
    option_count, strike_nok = settlement_inputs

    option_meta = dict(base.get("option") or {})
    accounting_liability_nok = (
        Decimal(str(option_meta.get("accounting_liability_mnok") or "0")) * MILLION
    )
    cash_fx_nok = (
        Decimal(str((base.get("cash_fx") or {}).get("adjustment_mnok") or "0"))
        * MILLION
    )
    operating = base.get("operating_costs") or {}
    base_cost_nok, conservative_cost_nok, public_operating = (
        _apply_conservative_cost_floor(operating)
    )

    life360 = await life360_nav_adjustment(repository, as_of_date=as_of_date)
    life360_month_effect = None
    if month_row is not None:
        month_state = await life360_nav_adjustment(
            repository, as_of_date=str(month_row["as_of_date"])
        )
        life360_month_effect = _life360_month_price_effect(
            month_state,
            life360,
            int(month_row["shares_outstanding"]),
            int(row["shares_outstanding"]),
        )
    life360_adjustment_nok = (
        Decimal(str(life360.get("adjustment_nok") or "0"))
        if life360.get("ready")
        else Decimal("0")
    )

    full_nav_total_nok = Decimal(str(row["nav_total_nok"]))
    shares_outstanding = int(row["shares_outstanding"])
    otec_price_nok = (
        Decimal(str(row["otec_price_nok"]))
        if row.get("otec_price_nok") is not None
        else None
    )

    base_pre_option_total = (
        full_nav_total_nok
        + accounting_liability_nok
        + cash_fx_nok
        + life360_adjustment_nok
        - base_cost_nok
    )
    conservative_pre_option_total = (
        full_nav_total_nok
        + accounting_liability_nok
        + cash_fx_nok
        + life360_adjustment_nok
        - conservative_cost_nok
    )
    settlement = nav_cash_settlement(
        pre_option_total_nok=base_pre_option_total,
        shares_outstanding=shares_outstanding,
        option_count=option_count,
        strike_nok=strike_nok,
    )
    conservative_settlement = nav_cash_settlement(
        pre_option_total_nok=conservative_pre_option_total,
        shares_outstanding=shares_outstanding,
        option_count=option_count,
        strike_nok=strike_nok,
    )

    economic_total_nok = Decimal(
        str(settlement["economic_total_after_settlement_nok"])
    )
    economic_per_share = Decimal(str(settlement["nav_after_option_per_share_nok"]))
    conservative_per_share = Decimal(
        str(conservative_settlement["nav_after_option_per_share_nok"])
    )

    option_meta.update(
        {
            "black_scholes_gross_mnok": option_meta.get("economic_value_mnok"),
            "settlement_mnok": _float(
                Decimal(str(settlement["settlement_nok"])) / MILLION
            ),
            "conservative_settlement_mnok": _float(
                Decimal(str(conservative_settlement["settlement_nok"])) / MILLION
            ),
            "settlement_per_option_nok": _float(
                Decimal(str(settlement["settlement_per_option_nok"]))
            ),
            "option_count": option_count,
            "strike_nok": _float(strike_nok),
            "nav_before_option_per_share_nok": _float(
                Decimal(str(settlement["nav_before_option_per_share_nok"]))
            ),
            "nav_after_option_per_share_nok": _float(economic_per_share),
            "method": settlement["method"],
            "assumption": settlement["assumption"],
            "full_realisation_scenario": True,
        }
    )

    live_composition = await live_nav_composition(repository, as_of_date)
    composition_ready = bool(live_composition.get("ready"))
    if composition_ready:
        composition_nav = Decimal(str(live_composition.get("nav_per_share") or "0"))
        if abs(composition_nav - economic_per_share) > LIVE_COMPOSITION_TOLERANCE_NOK:
            composition_ready = False
            live_composition = {
                "ready": False,
                "reason": "live_composition_nav_mismatch",
                "date": as_of_date,
                "composition_nav_per_share": float(composition_nav),
                "economic_nav_per_share": float(economic_per_share),
            }

    base.update(
        {
            "quality": (
                "NAV_SETTLEMENT_SCENARIO_LIFE360_MARK_TO_MARKET"
                if life360.get("ready")
                else "NAV_SETTLEMENT_SCENARIO"
            ),
            "nav_total_mnok": _float(economic_total_nok / MILLION),
            "nav_per_share": _float(economic_per_share),
            "calculated_at": str(row.get("updated_at") or row["created_at"]),
            "shares_outstanding": shares_outstanding,
            "discount_pct": _discount_pct(otec_price_nok, economic_per_share),
            "conservative_nav_per_share": _float(conservative_per_share),
            "conservative_discount_pct": _discount_pct(
                otec_price_nok, conservative_per_share
            ),
            "composition_ready": composition_ready,
            "composition_date": (
                live_composition.get("date") if composition_ready else None
            ),
            "composition": (
                live_composition.get("composition") if composition_ready else None
            ),
            "composition_reconciliation_residual_mnok": (
                live_composition.get("reconciliation_residual_mnok")
                if composition_ready
                else None
            ),
            "composition_split_status": live_composition.get("composition_split_status"),
            "composition_display_policy": live_composition.get("display_policy"),
            "composition_status": live_composition,
            "option": option_meta,
            "life360": {
                **_life360_public(life360),
                "nav_effect_1m_per_share_nok": life360_month_effect,
            },
            "operating_costs": public_operating,
            "economic_cash_note": (
                "Kontantbeholdningen er før det hypotetiske opsjonsoppgjøret; scenarioet "
                "forutsetter samtidig full Bemobi-realisering og retur av proveny."
            ),
            "note": (
                "Investor-NAV replaces the Black-Scholes option overhang with a self-consistent "
                "full-realisation cash-settlement scenario. From the 2025 fair-value reporting "
                "anchor it also replaces the embedded Life360 value with current LIF market value. "
                "The conservative operating-cost scenario is floored at the BASE run-rate so it "
                "can never increase NAV. FULL NAV and the accounting option liability remain "
                "unchanged for report reconciliation."
            ),
        }
    )
    return base