from __future__ import annotations

from decimal import Decimal
from typing import Any

from life360_nav import _usd_nok, life360_nav_adjustment
from market_attribution import symmetric_two_factor_attribution
from nav_refresh import _holding, _nearest_fx, _preferred_price
from nav_waterfall_settlement import nav_waterfall_summary as base_nav_waterfall_summary

MILLION = Decimal("1000000")
ATTRIBUTION_TOLERANCE_NOK = Decimal("1000")
RECONCILIATION_TOLERANCE_NOK = Decimal("0.01")


def _component_amount_nok(component: dict[str, Any]) -> Decimal:
    return Decimal(str(component.get("amount_mnok") or "0")) * MILLION


def _breakdown(label: str, amount_nok: Decimal, anchor_shares: int) -> dict[str, Any]:
    return {
        "label": label,
        "amountMnok": float(amount_nok / MILLION),
        "perShareNok": float(amount_nok / Decimal(anchor_shares)),
    }


def _reconcile(result: dict[str, Any]) -> None:
    anchor = result.get("anchor") or {}
    current = result.get("current") or {}
    anchor_total = Decimal(str(anchor.get("economic_nav_total_mnok") or "0")) * MILLION
    current_total = Decimal(str(current.get("economic_nav_total_mnok") or "0")) * MILLION
    anchor_per_share = Decimal(str(anchor.get("economic_nav_per_share_nok") or "0"))
    current_per_share = Decimal(str(current.get("economic_nav_per_share_nok") or "0"))

    component_total = sum(
        (
            _component_amount_nok(item)
            for item in result.get("components") or []
            if item.get("amount_mnok") is not None
        ),
        Decimal("0"),
    )
    per_share_components = sum(
        (
            Decimal(str(item.get("per_share_nok") or "0"))
            for item in result.get("components") or []
            if item.get("per_share_nok") is not None
        ),
        Decimal("0"),
    )
    total_change = current_total - anchor_total
    total_residual = total_change - component_total
    per_share_residual = current_per_share - anchor_per_share - per_share_components

    result["quality"] = (
        "RECONCILED"
        if abs(total_residual) < RECONCILIATION_TOLERANCE_NOK
        else "RESIDUAL"
    )
    result["reconciliation"] = {
        "component_total_mnok": float(component_total / MILLION),
        "total_change_mnok": float(total_change / MILLION),
        "residual_mnok": float(total_residual / MILLION),
        "per_share_residual_nok": float(per_share_residual),
    }


def apply_market_attribution(
    result: dict[str, Any],
    *,
    bemobi_attribution: dict[str, Any] | None = None,
    life360_attribution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reclassify market drivers without changing economic NAV itself."""
    if not result.get("ready"):
        return result

    anchor_shares = int((result.get("anchor") or {}).get("shares_outstanding") or 0)
    if anchor_shares <= 0:
        return result

    components = [dict(item) for item in result.get("components") or []]

    if bemobi_attribution and bemobi_attribution.get("ready"):
        for item in components:
            if str(item.get("key")) != "bemobi":
                continue
            item["label"] = "Bemobi – netto effekt"
            item["breakdown"] = [
                _breakdown(
                    "BMOB3-kurs",
                    Decimal(str(bemobi_attribution["price_effect_nok"])),
                    anchor_shares,
                ),
                _breakdown(
                    "BRL/NOK",
                    Decimal(str(bemobi_attribution["fx_effect_nok"])),
                    anchor_shares,
                ),
            ]
            item["note"] = (
                "Netto endring i Otellos Bemobi-markedsverdi siden rapportankeret. "
                "Aksjekurs og BRL/NOK fordeles symmetrisk, slik at kryssleddet ikke "
                "avhenger av hvilken driver som beregnes først."
            )
            break
        result["bemobi_attribution"] = bemobi_attribution

    if life360_attribution and life360_attribution.get("ready"):
        embedded_fx_nok = Decimal(str(life360_attribution["embedded_fx_nok"]))
        life_component = next(
            (item for item in components if str(item.get("key")) == "life360_mark_to_market"),
            None,
        )
        ona_component = next(
            (item for item in components if str(item.get("key")) == "ona_ex_option"),
            None,
        )
        if life_component is not None and ona_component is not None:
            old_life_amount = _component_amount_nok(life_component)
            expected_adjustment = Decimal(str(life360_attribution["mark_to_market_adjustment_nok"]))
            if abs(old_life_amount - expected_adjustment) <= ATTRIBUTION_TOLERANCE_NOK:
                life_total = Decimal(str(life360_attribution["total_change_nok"]))
                life_component["key"] = "life360_net"
                life_component["label"] = "Life360 – netto effekt"
                life_component["amount_mnok"] = float(life_total / MILLION)
                life_component["per_share_nok"] = float(life_total / Decimal(anchor_shares))
                life_component["breakdown"] = [
                    _breakdown(
                        "LIF-kurs",
                        Decimal(str(life360_attribution["price_effect_nok"])),
                        anchor_shares,
                    ),
                    _breakdown(
                        "USD/NOK",
                        Decimal(str(life360_attribution["fx_effect_nok"])),
                        anchor_shares,
                    ),
                ]
                life_component["note"] = (
                    "Netto endring i verdien av Otellos Life360-aksjer siden rapportankeret. "
                    "USD/NOK-effekten som allerede ligger i den videreførte ONA-posten "
                    "reklassifiseres hit; økonomisk NAV endres ikke."
                )

                ona_after = _component_amount_nok(ona_component) - embedded_fx_nok
                ona_component["amount_mnok"] = float(ona_after / MILLION)
                ona_component["per_share_nok"] = float(ona_after / Decimal(anchor_shares))
                ona_component["note"] = (
                    str(ona_component.get("note") or "")
                    + " Life360s identifiserte USD/NOK-effekt er reklassifisert til "
                    "Life360 – netto effekt."
                ).strip()
                result["life360_attribution"] = life360_attribution

    result["components"] = components
    _reconcile(result)
    result["note"] = (
        str(result.get("note") or "")
        + " Børsnoterte investeringer forklares med nettoeffekt og symmetrisk "
        "attribusjon mellom aksjekurs og valuta når kildegrunnlaget kan avstemmes."
    ).strip()
    return result


async def _bemobi_attribution(
    repository,
    *,
    anchor_date: str,
    as_of_date: str,
    expected_change_nok: Decimal,
) -> dict[str, Any]:
    anchor_price = await _preferred_price(repository, "BMOB3", anchor_date)
    current_price = await _preferred_price(repository, "BMOB3", as_of_date)
    anchor_fx = await _nearest_fx(repository, "BRL", anchor_date)
    current_fx = await _nearest_fx(repository, "BRL", as_of_date)
    anchor_holding = await _holding(repository, anchor_date)
    current_holding = await _holding(repository, as_of_date)
    if any(value is None for value in (anchor_price, current_price, anchor_fx, current_fx, anchor_holding, current_holding)):
        return {"ready": False, "reason": "missing_bemobi_market_attribution_inputs"}

    assert anchor_price and current_price and anchor_fx and current_fx and anchor_holding and current_holding
    anchor_holding_shares = int(anchor_holding["shares"])
    current_holding_shares = int(current_holding["shares"])
    if anchor_holding_shares != current_holding_shares:
        return {
            "ready": False,
            "reason": "bemobi_holding_changed",
            "anchor_shares": anchor_holding_shares,
            "current_shares": current_holding_shares,
        }

    attribution = symmetric_two_factor_attribution(
        shares=anchor_holding_shares,
        anchor_price=Decimal(str(anchor_price["price"])),
        current_price=Decimal(str(current_price["price"])),
        anchor_fx=Decimal(str(anchor_fx["rate"])),
        current_fx=Decimal(str(current_fx["rate"])),
    )
    if abs(attribution["total_change_nok"] - expected_change_nok) > ATTRIBUTION_TOLERANCE_NOK:
        return {
            "ready": False,
            "reason": "bemobi_attribution_does_not_reconcile",
            "expected_change_nok": expected_change_nok,
            **attribution,
        }

    return {
        "ready": True,
        "method": "SYMMETRIC_TWO_FACTOR_SHAPLEY",
        "shares": anchor_holding_shares,
        "anchor_price_brl": Decimal(str(anchor_price["price"])),
        "current_price_brl": Decimal(str(current_price["price"])),
        "anchor_price_date": str(anchor_price["trading_date"]),
        "current_price_date": str(current_price["trading_date"]),
        "anchor_brl_nok": Decimal(str(anchor_fx["rate"])),
        "current_brl_nok": Decimal(str(current_fx["rate"])),
        "anchor_fx_date": str(anchor_fx["rate_date"]),
        "current_fx_date": str(current_fx["rate_date"]),
        **attribution,
    }


async def _life360_attribution(repository, *, as_of_date: str) -> dict[str, Any]:
    life360 = await life360_nav_adjustment(repository, as_of_date=as_of_date)
    if not life360.get("ready"):
        return {"ready": False, "reason": life360.get("reason") or "life360_not_ready"}

    anchor_date = str(life360["anchor_date"])
    anchor_fx_row = await _usd_nok(repository, anchor_date)
    if anchor_fx_row is None:
        return {"ready": False, "reason": "missing_life360_anchor_usd_nok"}

    shares = int(life360["shares"])
    anchor_price = Decimal(str(life360["anchor_price_usd"]))
    current_price = Decimal(str(life360["price"]))
    anchor_fx = Decimal(str(anchor_fx_row["rate"]))
    current_fx = Decimal(str(life360["fx_rate"]))
    attribution = symmetric_two_factor_attribution(
        shares=shares,
        anchor_price=anchor_price,
        current_price=current_price,
        anchor_fx=anchor_fx,
        current_fx=current_fx,
    )
    embedded_fx_nok = Decimal(shares) * anchor_price * (current_fx - anchor_fx)
    mark_to_market_adjustment = Decimal(str(life360["adjustment_nok"]))
    reconstructed_total = mark_to_market_adjustment + embedded_fx_nok
    if abs(attribution["total_change_nok"] - reconstructed_total) > ATTRIBUTION_TOLERANCE_NOK:
        return {
            "ready": False,
            "reason": "life360_attribution_does_not_reconcile",
            "reconstructed_total_nok": reconstructed_total,
            **attribution,
        }

    return {
        "ready": True,
        "method": "SYMMETRIC_TWO_FACTOR_SHAPLEY",
        "shares": shares,
        "anchor_date": anchor_date,
        "anchor_price_usd": anchor_price,
        "current_price_usd": current_price,
        "anchor_price_date": str(life360["anchor_price_date"]),
        "current_price_date": str(life360["price_date"]),
        "anchor_usd_nok": anchor_fx,
        "current_usd_nok": current_fx,
        "anchor_fx_date": str(anchor_fx_row["rate_date"]),
        "current_fx_date": str(life360["fx_date"]),
        "embedded_fx_nok": embedded_fx_nok,
        "mark_to_market_adjustment_nok": mark_to_market_adjustment,
        **attribution,
    }


async def nav_waterfall_summary(repository) -> dict[str, Any]:
    result = await base_nav_waterfall_summary(repository)
    if not result.get("ready"):
        return result

    anchor_date = str(result["anchor_date"])
    as_of_date = str(result["as_of_date"])
    bemobi_component = next(
        (item for item in result.get("components") or [] if str(item.get("key")) == "bemobi"),
        None,
    )
    bemobi = None
    if bemobi_component is not None:
        bemobi = await _bemobi_attribution(
            repository,
            anchor_date=anchor_date,
            as_of_date=as_of_date,
            expected_change_nok=_component_amount_nok(bemobi_component),
        )

    life360 = await _life360_attribution(repository, as_of_date=as_of_date)
    return apply_market_attribution(
        result,
        bemobi_attribution=bemobi,
        life360_attribution=life360,
    )
