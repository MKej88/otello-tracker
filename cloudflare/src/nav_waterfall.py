from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from typing import Any

from economic_nav import _cash_fx_revaluation, _latest_cost_anchors, _nearest_fx, _option_values

FULL_CALCULATION_VERSION = "full-market-nav-daily-v2"
MILLION = Decimal("1000000")
_BUYBACK_PERIOD_RE = re.compile(r"during\s+(20\d{2}-\d{2}-\d{2})[–-](20\d{2}-\d{2}-\d{2})", re.I)


def _float(value: Decimal | str | int | float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def _components(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


async def _full_row(repository, as_of_date: str):
    return await repository.first(
        """
        SELECT as_of_at, nav_total_nok, nav_per_share_nok, bemobi_value_nok,
               cash_estimate_nok, other_net_assets_nok, shares_outstanding,
               components_json, status
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='FULL'
          AND substr(as_of_at,1,10)=?
        ORDER BY as_of_at DESC, id DESC LIMIT 1
        """,
        (FULL_CALCULATION_VERSION, as_of_date),
    )


async def _modeled_buyback_cash(repository, *, anchor_date: str, as_of_date: str) -> dict[str, Any]:
    rows = await repository.all(
        """
        SELECT movement_date, amount_nok, description
        FROM cash_movements
        WHERE movement_type='OTELLO_BUYBACK'
          AND movement_date > ? AND movement_date <= ?
        ORDER BY movement_date, id
        """,
        (anchor_date, as_of_date),
    )
    total = Decimal("0")
    excluded = 0
    for row in rows:
        description = str(row.get("description") or "")
        match = _BUYBACK_PERIOD_RE.search(description)
        if match:
            period_start, _period_end = match.groups()
            if period_start <= anchor_date < str(row["movement_date"]):
                excluded += 1
                continue
        total += Decimal(str(row["amount_nok"]))
    return {
        "amount_nok": total,
        "movement_count": len(rows),
        "cross_anchor_excluded": excluded,
    }


def build_nav_waterfall(
    *,
    anchor_date: str,
    as_of_date: str,
    anchor_nav_total_nok: Decimal,
    anchor_bemobi_value_nok: Decimal,
    anchor_cash_nok: Decimal,
    anchor_other_net_assets_nok: Decimal,
    anchor_shares_outstanding: int,
    anchor_accounting_option_nok: Decimal,
    anchor_economic_option_nok: Decimal,
    current_nav_total_nok: Decimal,
    current_bemobi_value_nok: Decimal,
    current_cash_nok: Decimal,
    current_other_net_assets_nok: Decimal,
    current_shares_outstanding: int,
    current_accounting_option_nok: Decimal,
    current_economic_option_nok: Decimal,
    buyback_cash_nok: Decimal,
    cash_fx_adjustment_nok: Decimal,
    operating_cost_nok: Decimal,
    buyback_movement_count: int = 0,
    cross_anchor_buybacks_excluded: int = 0,
) -> dict[str, Any]:
    if anchor_shares_outstanding <= 0 or current_shares_outstanding <= 0:
        return {"ready": False, "reason": "invalid_share_count"}

    anchor_overhang = max(
        Decimal("0"), anchor_economic_option_nok - anchor_accounting_option_nok
    )
    current_overhang = max(
        Decimal("0"), current_economic_option_nok - current_accounting_option_nok
    )
    anchor_economic_total = anchor_nav_total_nok - anchor_overhang
    current_economic_total = (
        current_nav_total_nok
        + cash_fx_adjustment_nok
        - current_overhang
        - operating_cost_nok
    )

    cash_change = current_cash_nok - anchor_cash_nok
    other_cash_change = cash_change - buyback_cash_nok
    ona_ex_option_change = (
        current_other_net_assets_nok + current_accounting_option_nok
        - anchor_other_net_assets_nok - anchor_accounting_option_nok
    )
    accounting_option_effect = -(
        current_accounting_option_nok - anchor_accounting_option_nok
    )
    option_overhang_effect = -(current_overhang - anchor_overhang)

    amount_components: list[dict[str, Any]] = [
        {
            "key": "bemobi",
            "label": "Bemobi-verdi",
            "amount_nok": current_bemobi_value_nok - anchor_bemobi_value_nok,
            "note": "Markedsverdiendring i Otellos Bemobi-beholdning siden rapportankeret.",
        },
        {
            "key": "buyback_cash",
            "label": "Tilbakekjøp – kontantbruk",
            "amount_nok": buyback_cash_nok,
            "note": "Bekreftede tilbakekjøp som inngår i den modellerte kontantkurven etter rapportankeret.",
        },
        {
            "key": "other_cash",
            "label": "Øvrig kontantendring",
            "amount_nok": other_cash_change,
            "note": "Kontantendring i FULL NAV utover tilbakekjøp. Etter siste rapportanker består denne av kjente modellerte kontantstrømmer.",
        },
        {
            "key": "ona_ex_option",
            "label": "ONA ekskl. opsjon",
            "amount_nok": ona_ex_option_change,
            "note": "Endring i øvrige nettoeiendeler og Bemobi-fordringer før regnskapsført opsjonsforpliktelse.",
        },
        {
            "key": "accounting_option",
            "label": "Regnskapsført opsjon",
            "amount_nok": accounting_option_effect,
            "note": "NAV-effekt av endringen i den regnskapsførte opsjonsforpliktelsen.",
        },
        {
            "key": "cash_fx",
            "label": "Valuta på cash",
            "amount_nok": cash_fx_adjustment_nok,
            "note": "Kildebasert revaluering av kontantbeholdningens valutaeksponering siden rapportankeret.",
        },
        {
            "key": "option_overhang",
            "label": "Ekstra opsjonsoverheng",
            "amount_nok": option_overhang_effect,
            "note": "Endring i økonomisk opsjonsverdi som ikke allerede er reflektert i regnskapsført forpliktelse.",
        },
        {
            "key": "operating_costs",
            "label": "Estimert drift",
            "amount_nok": -operating_cost_nok,
            "note": "Kildebelagt estimert driftskostnad fra rapportankeret til dagens modellpunkt.",
        },
    ]

    anchor_shares = Decimal(anchor_shares_outstanding)
    current_shares = Decimal(current_shares_outstanding)
    components: list[dict[str, Any]] = []
    for item in amount_components:
        amount = Decimal(item["amount_nok"])
        components.append(
            {
                "key": item["key"],
                "label": item["label"],
                "amount_mnok": _float(amount / MILLION),
                "per_share_nok": _float(amount / anchor_shares),
                "impact_kind": "TOTAL_AND_PER_SHARE",
                "note": item["note"],
            }
        )

    share_count_effect = (
        current_economic_total / current_shares
        - current_economic_total / anchor_shares
    )
    components.append(
        {
            "key": "share_count",
            "label": "Færre utestående aksjer",
            "amount_mnok": None,
            "per_share_nok": _float(share_count_effect),
            "impact_kind": "PER_SHARE_ONLY",
            "note": "Ren nevner-effekt: dagens økonomiske NAV fordeles på dagens utestående aksjer i stedet for aksjetallet ved rapportankeret.",
        }
    )

    components_total = sum(
        (Decimal(str(item["amount_nok"])) for item in amount_components),
        Decimal("0"),
    )
    total_change = current_economic_total - anchor_economic_total
    total_residual = total_change - components_total

    anchor_per_share = anchor_economic_total / anchor_shares
    current_per_share = current_economic_total / current_shares
    per_share_components = sum(
        (Decimal(str(item["per_share_nok"])) for item in components if item["per_share_nok"] is not None),
        Decimal("0"),
    )
    per_share_residual = current_per_share - anchor_per_share - per_share_components

    return {
        "ready": True,
        "quality": "RECONCILED" if abs(total_residual) < Decimal("0.01") else "RESIDUAL",
        "anchor_date": anchor_date,
        "as_of_date": as_of_date,
        "anchor": {
            "full_nav_total_mnok": _float(anchor_nav_total_nok / MILLION),
            "full_nav_per_share_nok": _float(anchor_nav_total_nok / anchor_shares),
            "economic_nav_total_mnok": _float(anchor_economic_total / MILLION),
            "economic_nav_per_share_nok": _float(anchor_per_share),
            "shares_outstanding": anchor_shares_outstanding,
            "option_overhang_mnok": _float(anchor_overhang / MILLION),
        },
        "current": {
            "full_nav_total_mnok": _float(current_nav_total_nok / MILLION),
            "full_nav_per_share_nok": _float(current_nav_total_nok / current_shares),
            "economic_nav_total_mnok": _float(current_economic_total / MILLION),
            "economic_nav_per_share_nok": _float(current_per_share),
            "shares_outstanding": current_shares_outstanding,
            "option_overhang_mnok": _float(current_overhang / MILLION),
        },
        "change": {
            "economic_nav_total_mnok": _float(total_change / MILLION),
            "economic_nav_per_share_nok": _float(current_per_share - anchor_per_share),
            "shares_outstanding": current_shares_outstanding - anchor_shares_outstanding,
        },
        "components": components,
        "buybacks": {
            "modeled_cash_mnok": _float(buyback_cash_nok / MILLION),
            "movement_count": buyback_movement_count,
            "cross_anchor_excluded": cross_anchor_buybacks_excluded,
        },
        "reconciliation": {
            "component_total_mnok": _float(components_total / MILLION),
            "total_change_mnok": _float(total_change / MILLION),
            "residual_mnok": _float(total_residual / MILLION),
            "per_share_residual_nok": _float(per_share_residual),
        },
        "note": (
            "Per-aksje-broen er matematisk avstemt: verdiendringer regnes mot aksjetallet ved rapportankeret, "
            "og endringen i antall utestående aksjer vises som en separat nevner-effekt. Modellen skiller "
            "tilbakekjøpskontanter fra øvrig cash for å unngå dobbelttelling."
        ),
    }


async def nav_waterfall_summary(repository) -> dict[str, Any]:
    latest = await repository.first(
        """
        SELECT MAX(substr(as_of_at,1,10)) AS max_date
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='FULL'
        """,
        (FULL_CALCULATION_VERSION,),
    )
    as_of_date = latest.get("max_date") if latest is not None else None
    if as_of_date is None:
        return {"ready": False, "reason": "missing_full_nav"}

    anchor = await repository.first(
        """
        SELECT as_of_date FROM cash_anchors
        WHERE anchor_type='REPORTED' AND as_of_date <= ?
        ORDER BY as_of_date DESC, id DESC LIMIT 1
        """,
        (as_of_date,),
    )
    if anchor is None:
        return {"ready": False, "reason": "missing_reported_cash_anchor"}
    anchor_date = str(anchor["as_of_date"])

    current = await _full_row(repository, str(as_of_date))
    anchor_row = await _full_row(repository, anchor_date)
    if current is None:
        return {"ready": False, "reason": "missing_current_full_nav"}
    if anchor_row is None:
        return {
            "ready": False,
            "reason": "missing_anchor_full_nav",
            "anchor_date": anchor_date,
        }

    current_options = _option_values(_components(current.get("components_json")))
    anchor_options = _option_values(_components(anchor_row.get("components_json")))
    if current_options is None or anchor_options is None:
        return {"ready": False, "reason": "missing_option_values"}
    current_accounting_option, current_economic_option = current_options
    anchor_accounting_option, anchor_economic_option = anchor_options

    cash_fx = await _cash_fx_revaluation(
        repository,
        cash_anchor_date=anchor_date,
        as_of_date=str(as_of_date),
    )
    if not cash_fx.get("ready"):
        return cash_fx

    usd_nok = await _nearest_fx(repository, "USD", str(as_of_date))
    if usd_nok is None:
        return {"ready": False, "reason": "missing_recent_usd_nok"}
    cost_anchors = await _latest_cost_anchors(repository, str(as_of_date))
    base_cost = cost_anchors.get("BASE")
    if base_cost is None:
        return {"ready": False, "reason": "missing_operating_cost_anchor"}
    days_since_anchor = max(
        0,
        (date.fromisoformat(str(as_of_date)) - date.fromisoformat(anchor_date)).days,
    )
    operating_cost_nok = (
        base_cost["amount_usd_decimal"]
        / Decimal(base_cost["period_days_int"])
        * Decimal(days_since_anchor)
        * Decimal(str(usd_nok["rate"]))
    )

    buybacks = await _modeled_buyback_cash(
        repository,
        anchor_date=anchor_date,
        as_of_date=str(as_of_date),
    )

    return build_nav_waterfall(
        anchor_date=anchor_date,
        as_of_date=str(as_of_date),
        anchor_nav_total_nok=Decimal(str(anchor_row["nav_total_nok"])),
        anchor_bemobi_value_nok=Decimal(str(anchor_row["bemobi_value_nok"])),
        anchor_cash_nok=Decimal(str(anchor_row["cash_estimate_nok"])),
        anchor_other_net_assets_nok=Decimal(str(anchor_row["other_net_assets_nok"])),
        anchor_shares_outstanding=int(anchor_row["shares_outstanding"]),
        anchor_accounting_option_nok=anchor_accounting_option,
        anchor_economic_option_nok=anchor_economic_option,
        current_nav_total_nok=Decimal(str(current["nav_total_nok"])),
        current_bemobi_value_nok=Decimal(str(current["bemobi_value_nok"])),
        current_cash_nok=Decimal(str(current["cash_estimate_nok"])),
        current_other_net_assets_nok=Decimal(str(current["other_net_assets_nok"])),
        current_shares_outstanding=int(current["shares_outstanding"]),
        current_accounting_option_nok=current_accounting_option,
        current_economic_option_nok=current_economic_option,
        buyback_cash_nok=buybacks["amount_nok"],
        cash_fx_adjustment_nok=Decimal(str(cash_fx["adjustment_nok"])),
        operating_cost_nok=operating_cost_nok,
        buyback_movement_count=int(buybacks["movement_count"]),
        cross_anchor_buybacks_excluded=int(buybacks["cross_anchor_excluded"]),
    )
