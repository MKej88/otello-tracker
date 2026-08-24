from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from economic_nav import _cash_fx_revaluation, _latest_cost_anchors, _nearest_fx, _option_values
from life360_nav import life360_nav_adjustment
from option_settlement import MILLION, nav_cash_settlement, settlement_inputs_from_components

FULL_CALCULATION_VERSION = "full-market-nav-daily-v2"
MAX_ESTIMATED_HISTORY_POINTS = 72


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


def _component(key: str, label: str, amount_nok: Decimal, shares: int, formula: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "amount_mnok": _float(amount_nok / MILLION),
        "per_share_nok": _float(amount_nok / Decimal(shares)),
        "formula": formula,
        "details": details or {},
    }


def _pick_dates(dates: list[str], limit: int = MAX_ESTIMATED_HISTORY_POINTS) -> list[str]:
    if len(dates) <= limit:
        return dates
    indexes = sorted({round(i * (len(dates) - 1) / (limit - 1)) for i in range(limit)})
    return [dates[i] for i in indexes]


async def _full_row(repository, day: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT substr(as_of_at,1,10) AS date, nav_total_nok, nav_per_share_nok,
               otec_price_nok, bemobi_value_nok, cash_estimate_nok,
               other_net_assets_nok, shares_outstanding, components_json
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='FULL'
          AND substr(as_of_at,1,10)=?
        ORDER BY as_of_at DESC, id DESC LIMIT 1
        """,
        (FULL_CALCULATION_VERSION, day),
    )


async def _estimated_point(repository, day: str) -> dict[str, Any]:
    row = await _full_row(repository, day)
    if row is None:
        return {"ready": False, "reason": "missing_full_nav_row", "date": day}
    components = _components(row.get("components_json"))
    option_values = _option_values(components)
    settlement_inputs = settlement_inputs_from_components(components)
    if option_values is None or settlement_inputs is None:
        return {"ready": False, "reason": "missing_option_inputs", "date": day}
    accounting_option_nok, _ = option_values
    option_count, strike_nok = settlement_inputs
    anchor = await repository.first(
        "SELECT as_of_date FROM cash_anchors WHERE anchor_type='REPORTED' AND as_of_date<=? ORDER BY as_of_date DESC,id DESC LIMIT 1",
        (day,),
    )
    if anchor is None:
        return {"ready": False, "reason": "missing_reported_cash_anchor", "date": day}
    cash_anchor_date = str(anchor["as_of_date"])
    usd_nok = await _nearest_fx(repository, "USD", day)
    base_cost = (await _latest_cost_anchors(repository, day)).get("BASE")
    if usd_nok is None or base_cost is None:
        return {"ready": False, "reason": "missing_estimated_nav_anchor", "date": day}
    cash_fx = await _cash_fx_revaluation(repository, cash_anchor_date=cash_anchor_date, as_of_date=day)
    if not cash_fx.get("ready"):
        return {"ready": False, "reason": cash_fx.get("reason") or "cash_fx_not_ready", "date": day}
    days_since_anchor = max(0, (date.fromisoformat(day) - date.fromisoformat(cash_anchor_date)).days)
    operating_cost_nok = (
        Decimal(str(base_cost["amount_usd_decimal"])) / Decimal(int(base_cost["period_days_int"]))
        * Decimal(days_since_anchor) * Decimal(str(usd_nok["rate"]))
    )
    cash_fx_nok = Decimal(str(cash_fx.get("adjustment_nok") or "0"))
    life360 = await life360_nav_adjustment(repository, as_of_date=day)
    life360_adjustment_nok = Decimal(str(life360.get("adjustment_nok") or "0")) if life360.get("ready") else Decimal("0")
    full_nav_total_nok = Decimal(str(row["nav_total_nok"]))
    bemobi_nok = Decimal(str(row.get("bemobi_value_nok") or "0"))
    reported_cash_nok = Decimal(str(row.get("cash_estimate_nok") or "0"))
    reported_ona_nok = Decimal(str(row.get("other_net_assets_nok") or "0"))
    shares = int(row["shares_outstanding"])
    if shares <= 0:
        return {"ready": False, "reason": "invalid_share_count", "date": day}
    cash_nok = reported_cash_nok + cash_fx_nok - operating_cost_nok
    ona_ex_option_nok = reported_ona_nok + accounting_option_nok
    pre_option_total_nok = full_nav_total_nok + accounting_option_nok + cash_fx_nok + life360_adjustment_nok - operating_cost_nok
    settlement = nav_cash_settlement(pre_option_total_nok=pre_option_total_nok, shares_outstanding=shares, option_count=option_count, strike_nok=strike_nok)
    settlement_nok = Decimal(str(settlement["settlement_nok"]))
    estimated_total_nok = Decimal(str(settlement["economic_total_after_settlement_nok"]))
    estimated_per_share = Decimal(str(settlement["nav_after_option_per_share_nok"]))
    otec_price = Decimal(str(row["otec_price_nok"])) if row.get("otec_price_nok") is not None else None
    discount = (Decimal("1") - otec_price / estimated_per_share) * Decimal("100") if otec_price is not None and estimated_per_share > 0 else None
    composition = [
        _component("bemobi", "Bemobi", bemobi_nok, shares, "Bemobi-aksjer × BMOB3-kurs × BRL/NOK"),
        _component("cash", "Estimert kontantbeholdning", cash_nok, shares, "Rapportert kontantbeholdning + valutaeffekt − estimert drift siden rapport", {"reported_cash_mnok": _float(reported_cash_nok / MILLION), "cash_fx_adjustment_mnok": _float(cash_fx_nok / MILLION), "operating_cost_mnok": _float(operating_cost_nok / MILLION), "cash_anchor_date": cash_anchor_date}),
        _component("ona", "Øvrige nettoeiendeler", ona_ex_option_nok, shares, "Regnskapsmessig ONA + regnskapsført opsjonsforpliktelse", {"reported_ona_mnok": _float(reported_ona_nok / MILLION), "accounting_option_liability_mnok": _float(accounting_option_nok / MILLION)}),
        _component("life360", "Life360 mark-to-market", life360_adjustment_nok, shares, "Dagens verdi av LIF − Life360-verdi innebygd i siste rapporterte ONA", {"active": bool(life360.get("ready")), "price_date": life360.get("price_date"), "anchor_date": life360.get("anchor_date")}),
        _component("options", "Opsjoner – estimert kontantoppgjør", -settlement_nok, shares, "Selvkonsistent kontantoppgjør ved Estimert NAV", {"option_count": option_count, "strike_nok": _float(strike_nok), "settlement_mnok": _float(settlement_nok / MILLION)}),
    ]
    composition_total = sum((Decimal(str(item["amount_mnok"])) * MILLION for item in composition), Decimal("0"))
    return {
        "ready": True, "date": day, "nav_total_mnok": _float(estimated_total_nok / MILLION),
        "nav_per_share": _float(estimated_per_share), "otec_price": _float(otec_price), "discount_pct": _float(discount),
        "shares_outstanding": shares, "accounting_nav_per_share": _float(row.get("nav_per_share_nok")),
        "composition": composition, "reconciliation_residual_mnok": _float((estimated_total_nok - composition_total) / MILLION),
        "model": "ESTIMATED_NAV_V1",
    }


def _change(start: dict[str, Any], current: dict[str, Any], requested_start: str) -> dict[str, Any]:
    start_by_key = {item["key"]: item for item in start.get("composition") or []}
    current_by_key = {item["key"]: item for item in current.get("composition") or []}
    drivers = []
    for key in ("bemobi", "cash", "ona", "life360", "options"):
        before, after = start_by_key.get(key), current_by_key.get(key)
        if before is None or after is None:
            continue
        delta = Decimal(str(after["per_share_nok"])) - Decimal(str(before["per_share_nok"]))
        drivers.append({"key": key, "label": after["label"], "per_share_nok": _float(delta), "start_per_share_nok": before["per_share_nok"], "current_per_share_nok": after["per_share_nok"]})
    total_change = Decimal(str(current["nav_per_share"])) - Decimal(str(start["nav_per_share"]))
    driver_total = sum((Decimal(str(item["per_share_nok"])) for item in drivers), Decimal("0"))
    return {"ready": True, "requested_start": requested_start, "resolved_start": start["date"], "current_date": current["date"], "start_nav_per_share": start["nav_per_share"], "current_nav_per_share": current["nav_per_share"], "change_per_share_nok": _float(total_change), "drivers": drivers, "reconciliation_residual_nok": _float(total_change - driver_total)}


async def estimated_nav_history(repository, *, days: int) -> dict[str, Any]:
    days = max(30, min(int(days), 3650))
    latest = await repository.first("SELECT MAX(substr(as_of_at,1,10)) AS max_date FROM nav_snapshots WHERE calculation_version=? AND nav_scope='FULL'", (FULL_CALCULATION_VERSION,))
    current_date = latest.get("max_date") if latest is not None else None
    if current_date is None:
        return {"ready": False, "reason": "missing_full_nav", "points": []}
    requested_start = (date.fromisoformat(str(current_date)) - timedelta(days=days)).isoformat()
    rows = await repository.all("SELECT DISTINCT substr(as_of_at,1,10) AS date FROM nav_snapshots WHERE calculation_version=? AND nav_scope='FULL' AND substr(as_of_at,1,10)>=? AND substr(as_of_at,1,10)<=? ORDER BY date", (FULL_CALCULATION_VERSION, requested_start, current_date))
    predecessor = await repository.first("SELECT MAX(substr(as_of_at,1,10)) AS date FROM nav_snapshots WHERE calculation_version=? AND nav_scope='FULL' AND substr(as_of_at,1,10)<=?", (FULL_CALCULATION_VERSION, requested_start))
    dates = [str(row["date"]) for row in rows if row.get("date")]
    predecessor_date = predecessor.get("date") if predecessor is not None else None
    if predecessor_date and predecessor_date not in dates:
        dates.insert(0, str(predecessor_date))
    if str(current_date) not in dates:
        dates.append(str(current_date))
    dates = _pick_dates(sorted(set(dates)))
    full_points, failures = [], []
    for day in dates:
        point = await _estimated_point(repository, day)
        if point.get("ready"):
            full_points.append(point)
        else:
            failures.append({"date": day, "reason": point.get("reason")})
    if not full_points:
        return {"ready": False, "reason": "estimated_history_not_ready", "requested_start": requested_start, "current_date": current_date, "failures": failures[:10], "points": []}
    current = next((item for item in reversed(full_points) if item["date"] == current_date), full_points[-1])
    start = min(full_points, key=lambda item: abs((date.fromisoformat(item["date"]) - date.fromisoformat(requested_start)).days))
    public_points = [{"date": item["date"], "nav_per_share": item["nav_per_share"], "otec_price": item["otec_price"], "discount_pct": item["discount_pct"]} for item in full_points]
    return {"ready": True, "model": "ESTIMATED_NAV_V1", "requested_start": requested_start, "from": public_points[0]["date"], "to": public_points[-1]["date"], "point_count": len(public_points), "points": public_points, "current": current, "change": _change(start, current, requested_start), "failures": failures[:10], "note": "Estimert NAV bruker samme kildebelagte investorlogikk historisk som i dagens Estimert NAV. Manglende historiske innganger gjettes ikke."}
