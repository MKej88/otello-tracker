from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.economic_nav import economic_nav_summary as accounting_economic_nav_summary
from app.life360_nav import life360_nav_adjustment
from app.nav.full_nav import FULL_CALCULATION_VERSION
from app.option_settlement import MILLION, nav_cash_settlement, settlement_inputs_from_components

CONSERVATIVE_COST_POLICY = "MAX_BASE_RUN_RATE_AND_SOURCE_CONSERVATIVE"


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _discount_pct(otec_price_nok: Decimal | None, nav_per_share_nok: Decimal) -> float | None:
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
        result["market_value_mnok"] = _float(Decimal(str(raw["market_value_nok"])) / MILLION)
    if raw.get("embedded_value_nok") is not None:
        result["embedded_value_mnok"] = _float(Decimal(str(raw["embedded_value_nok"])) / MILLION)
    return result


def _apply_conservative_cost_floor(operating: dict[str, Any]) -> tuple[Decimal, Decimal, dict[str, Any]]:
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
        public_operating["conservative_source_annualized_usd_m"] = source_conservative_annualized
    if base_annualized is not None and source_conservative_annualized is not None:
        public_operating["conservative_annualized_usd_m"] = max(
            float(base_annualized), float(source_conservative_annualized)
        )

    return base_cost_nok, conservative_cost_nok, public_operating


def economic_nav_summary(database_path: str | None = None) -> dict[str, Any]:
    """Investor NAV with option settlement and Life360 market-value overlays."""
    base = accounting_economic_nav_summary(database_path)
    if not base.get("ready"):
        return base

    as_of_date = str(base.get("as_of_date") or "")
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT as_of_at, created_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                   shares_outstanding, components_json
            FROM nav_snapshots
            WHERE calculation_version=? AND nav_scope='FULL'
              AND substr(as_of_at,1,10)=?
            ORDER BY as_of_at DESC, id DESC LIMIT 1
            """,
            (FULL_CALCULATION_VERSION, as_of_date),
        ).fetchone()
    if row is None:
        return {"ready": False, "reason": "missing_full_nav_row"}

    settlement_inputs = settlement_inputs_from_components(_components(row["components_json"]))
    if settlement_inputs is None:
        return {
            "ready": False,
            "reason": "missing_option_settlement_inputs",
            "as_of_date": as_of_date,
        }
    option_count, strike_nok = settlement_inputs

    option_meta = dict(base.get("option") or {})
    accounting_liability_nok = Decimal(str(option_meta.get("accounting_liability_mnok") or "0")) * MILLION
    cash_fx_nok = Decimal(str((base.get("cash_fx") or {}).get("adjustment_mnok") or "0")) * MILLION
    operating = base.get("operating_costs") or {}
    base_cost_nok, conservative_cost_nok, public_operating = _apply_conservative_cost_floor(
        operating
    )

    life360 = life360_nav_adjustment(as_of_date=as_of_date, database_path=database_path)
    life360_adjustment_nok = (
        Decimal(str(life360.get("adjustment_nok") or "0")) if life360.get("ready") else Decimal("0")
    )

    full_nav_total_nok = Decimal(str(row["nav_total_nok"]))
    shares_outstanding = int(row["shares_outstanding"])
    otec_price_nok = (
        Decimal(str(row["otec_price_nok"])) if row["otec_price_nok"] is not None else None
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

    economic_per_share = Decimal(str(settlement["nav_after_option_per_share_nok"]))
    conservative_per_share = Decimal(str(conservative_settlement["nav_after_option_per_share_nok"]))

    option_meta.update(
        {
            "black_scholes_gross_mnok": option_meta.get("economic_value_mnok"),
            "settlement_mnok": _float(Decimal(str(settlement["settlement_nok"])) / MILLION),
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

    base.update(
        {
            "quality": (
                "NAV_SETTLEMENT_SCENARIO_LIFE360_MARK_TO_MARKET"
                if life360.get("ready")
                else "NAV_SETTLEMENT_SCENARIO"
            ),
            "nav_per_share": _float(economic_per_share),
            "calculated_at": str(row["created_at"]),
            "shares_outstanding": shares_outstanding,
            "discount_pct": _discount_pct(otec_price_nok, economic_per_share),
            "conservative_nav_per_share": _float(conservative_per_share),
            "conservative_discount_pct": _discount_pct(otec_price_nok, conservative_per_share),
            "option": option_meta,
            "life360": _life360_public(life360),
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
