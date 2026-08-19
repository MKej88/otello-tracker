from __future__ import annotations

from decimal import Decimal
from typing import Any

from nav_waterfall_investor import nav_waterfall_summary as investor_waterfall_summary
from option_settlement import MILLION, nav_cash_settlement, settlement_inputs_from_daily_row


def _amount_nok(components: list[dict[str, Any]], key: str) -> Decimal:
    for item in components:
        if str(item.get("key")) == key:
            return Decimal(str(item.get("amount_mnok") or "0")) * MILLION
    return Decimal("0")


async def _option_row(repository, day: str):
    return await repository.first(
        """
        SELECT option_liability_nok, option_strike_nok, option_inputs_json
        FROM other_net_assets_daily_estimates
        WHERE estimate_date=? LIMIT 1
        """,
        (day,),
    )


def apply_nav_settlement_waterfall(
    result: dict[str, Any],
    *,
    anchor_option_inputs: tuple[Decimal, int, Decimal],
    current_option_inputs: tuple[Decimal, int, Decimal],
) -> dict[str, Any]:
    if not result.get("ready"):
        return result

    anchor = dict(result.get("anchor") or {})
    current = dict(result.get("current") or {})
    anchor_shares = int(anchor.get("shares_outstanding") or 0)
    current_shares = int(current.get("shares_outstanding") or 0)
    if anchor_shares <= 0 or current_shares <= 0:
        return {"ready": False, "reason": "invalid_share_count"}

    anchor_full_nok = Decimal(str(anchor.get("full_nav_total_mnok") or "0")) * MILLION
    current_full_nok = Decimal(str(current.get("full_nav_total_mnok") or "0")) * MILLION
    anchor_accounting, anchor_option_count, anchor_strike = anchor_option_inputs
    current_accounting, current_option_count, current_strike = current_option_inputs

    components = list(result.get("components") or [])
    cash_fx_nok = _amount_nok(components, "cash_fx")
    operating_effect_nok = _amount_nok(components, "operating_costs")

    anchor_pre_option_nok = anchor_full_nok + anchor_accounting
    current_pre_option_nok = (
        current_full_nok + current_accounting + cash_fx_nok + operating_effect_nok
    )
    anchor_settlement = nav_cash_settlement(
        pre_option_total_nok=anchor_pre_option_nok,
        shares_outstanding=anchor_shares,
        option_count=anchor_option_count,
        strike_nok=anchor_strike,
    )
    current_settlement = nav_cash_settlement(
        pre_option_total_nok=current_pre_option_nok,
        shares_outstanding=current_shares,
        option_count=current_option_count,
        strike_nok=current_strike,
    )

    anchor_settlement_nok = Decimal(str(anchor_settlement["settlement_nok"]))
    current_settlement_nok = Decimal(str(current_settlement["settlement_nok"]))
    anchor_economic_nok = Decimal(str(anchor_settlement["economic_total_after_settlement_nok"]))
    current_economic_nok = Decimal(str(current_settlement["economic_total_after_settlement_nok"]))
    option_effect_nok = -(current_settlement_nok - anchor_settlement_nok)

    settlement_component = {
        "key": "option_settlement",
        "label": "Opsjoner – kontantoppgjør ved NAV",
        "amount_mnok": float(option_effect_nok / MILLION),
        "per_share_nok": float(option_effect_nok / Decimal(anchor_shares)),
        "impact_kind": "TOTAL_AND_PER_SHARE",
        "note": (
            "Endring i hypotetisk kontantoppgjør ved full Bemobi-realisering. "
            "Exercise-dagens OTEC-kurs antas lik økonomisk NAV per aksje etter oppgjøret."
        ),
    }

    rebuilt: list[dict[str, Any]] = []
    inserted = False
    for item in components:
        key = str(item.get("key"))
        if key == "accounting_option":
            if not inserted:
                rebuilt.append(settlement_component)
                inserted = True
            continue
        if key == "option_overhang":
            if not inserted:
                rebuilt.append(settlement_component)
                inserted = True
            continue
        if key == "share_count":
            continue
        rebuilt.append(item)
    if not inserted:
        rebuilt.append(settlement_component)

    share_count_effect = (
        current_economic_nok / Decimal(current_shares)
        - current_economic_nok / Decimal(anchor_shares)
    )
    rebuilt.append(
        {
            "key": "share_count",
            "label": "Færre utestående aksjer",
            "amount_mnok": None,
            "per_share_nok": float(share_count_effect),
            "impact_kind": "PER_SHARE_ONLY",
            "note": "Ren nevner-effekt etter NAV-basert opsjonsoppgjør.",
        }
    )

    anchor_per_share = anchor_economic_nok / Decimal(anchor_shares)
    current_per_share = current_economic_nok / Decimal(current_shares)
    total_change = current_economic_nok - anchor_economic_nok
    component_total_nok = sum(
        (
            Decimal(str(item.get("amount_mnok"))) * MILLION
            for item in rebuilt
            if item.get("amount_mnok") is not None
        ),
        Decimal("0"),
    )
    total_residual = total_change - component_total_nok
    per_share_components = sum(
        (
            Decimal(str(item.get("per_share_nok")))
            for item in rebuilt
            if item.get("per_share_nok") is not None
        ),
        Decimal("0"),
    )
    per_share_residual = current_per_share - anchor_per_share - per_share_components

    anchor.update(
        {
            "economic_nav_total_mnok": float(anchor_economic_nok / MILLION),
            "economic_nav_per_share_nok": float(anchor_per_share),
            "option_settlement_mnok": float(anchor_settlement_nok / MILLION),
        }
    )
    current.update(
        {
            "economic_nav_total_mnok": float(current_economic_nok / MILLION),
            "economic_nav_per_share_nok": float(current_per_share),
            "option_settlement_mnok": float(current_settlement_nok / MILLION),
        }
    )
    result["anchor"] = anchor
    result["current"] = current
    result["components"] = rebuilt
    result["change"] = {
        "economic_nav_total_mnok": float(total_change / MILLION),
        "economic_nav_per_share_nok": float(current_per_share - anchor_per_share),
        "shares_outstanding": current_shares - anchor_shares,
    }
    result["quality"] = "RECONCILED" if abs(total_residual) < Decimal("0.01") else "RESIDUAL"
    result["reconciliation"] = {
        "component_total_mnok": float(component_total_nok / MILLION),
        "total_change_mnok": float(total_change / MILLION),
        "residual_mnok": float(total_residual / MILLION),
        "per_share_residual_nok": float(per_share_residual),
    }
    result["option_settlement"] = {
        "anchor_mnok": float(anchor_settlement_nok / MILLION),
        "current_mnok": float(current_settlement_nok / MILLION),
        "current_per_option_nok": float(Decimal(str(current_settlement["settlement_per_option_nok"]))),
        "anchor_strike_nok": float(anchor_strike),
        "current_strike_nok": float(current_strike),
        "option_count": current_option_count,
        "method": current_settlement["method"],
        "assumption": current_settlement["assumption"],
    }
    result["note"] = (
        str(result.get("note") or "")
        + " Investor-waterfallet erstatter regnskapsført opsjon og Black-Scholes-overheng "
        "med ett selvkonsistent kontantoppgjør ved NAV."
    ).strip()
    return result


async def nav_waterfall_summary(repository) -> dict[str, Any]:
    result = await investor_waterfall_summary(repository)
    if not result.get("ready"):
        return result

    anchor_date = str(result["anchor_date"])
    as_of_date = str(result["as_of_date"])
    anchor_inputs = settlement_inputs_from_daily_row(await _option_row(repository, anchor_date))
    current_inputs = settlement_inputs_from_daily_row(await _option_row(repository, as_of_date))
    if anchor_inputs is None or current_inputs is None:
        return {
            "ready": False,
            "reason": "missing_option_settlement_inputs",
            "anchor_date": anchor_date,
            "as_of_date": as_of_date,
        }
    return apply_nav_settlement_waterfall(
        result,
        anchor_option_inputs=anchor_inputs,
        current_option_inputs=current_inputs,
    )
