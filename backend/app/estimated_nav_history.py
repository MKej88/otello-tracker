from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.economic_nav import (
    _cash_fx_revaluation,
    _latest_cost_anchors,
    _nearest_fx,
    _option_values,
)
from app.estimated_nav_attribution import (
    ATTRIBUTION_TOLERANCE_NOK,
    bemobi_market_attribution as _bemobi_market_attribution,
    symmetric_two_factor_attribution,
)
from app.life360_nav import life360_nav_adjustment
from app.nav.full_nav import FULL_CALCULATION_VERSION
from app.option_settlement import MILLION, nav_cash_settlement, settlement_inputs_from_components

__all__ = ["symmetric_two_factor_attribution"]

MAX_ESTIMATED_HISTORY_POINTS = 72
_BUYBACK_PERIOD_RE = re.compile(
    r"during\s+(20\d{2}-\d{2}-\d{2})[–-](20\d{2}-\d{2}-\d{2})",
    re.I,
)


def _float(value: Decimal | str | int | float | None) -> float | None:
    return None if value is None else float(Decimal(str(value)))


def _components(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _component(
    key: str,
    label: str,
    amount_nok: Decimal,
    shares: int,
    formula: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
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


def _composition_amount_nok(point: dict[str, Any], key: str) -> Decimal:
    for item in point.get("composition") or []:
        if str(item.get("key")) == key:
            return Decimal(str(item.get("amount_mnok") or "0")) * MILLION
    return Decimal("0")


def _composition_details(point: dict[str, Any], key: str) -> dict[str, Any]:
    for item in point.get("composition") or []:
        if item.get("key") == key and isinstance(item.get("details"), dict):
            return item["details"]
    return {}


def _driver(
    *,
    key: str,
    label: str,
    amount_nok: Decimal,
    per_share_scale: Decimal,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "amount_mnok": _float(amount_nok / MILLION),
        "per_share_nok": _float(amount_nok * per_share_scale),
        "impact_kind": "TOTAL_AND_PER_SHARE",
        "details": details or {},
    }


def _share_count_driver(
    *,
    start_total_nok: Decimal,
    current_total_nok: Decimal,
    start_shares: int,
    current_shares: int,
) -> dict[str, Any]:
    start_count = Decimal(start_shares)
    current_count = Decimal(current_shares)
    effect = (
        (start_total_nok + current_total_nok)
        / Decimal("2")
        * (Decimal("1") / current_count - Decimal("1") / start_count)
    )
    reduced = start_shares - current_shares
    label = (
        "Tilbakekjøp – færre utestående aksjer"
        if reduced >= 0
        else "Endring i utestående aksjer"
    )
    return {
        "key": "buyback_shares",
        "label": label,
        "amount_mnok": None,
        "per_share_nok": _float(effect),
        "impact_kind": "PER_SHARE_ONLY",
        "details": {
            "start_shares": start_shares,
            "current_shares": current_shares,
            "shares_reduced": reduced,
        },
    }


def _cash_breakdown(connection, *, start_date: str, current_date: str) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT movement_date, movement_type, amount_nok, description,
               external_movement_id, buyback_id
        FROM cash_movements
        WHERE movement_date > ? AND movement_date <= ?
          AND movement_type IN (
              'OTELLO_BUYBACK', 'OTELLO_BUYBACK_DAILY',
              'BEMOBI_DIVIDEND', 'BEMOBI_JCP', 'TAX'
          )
        ORDER BY movement_date, id
        """,
        (start_date, current_date),
    ).fetchall()
    copied = [dict(row) for row in rows]
    daily_buyback_ids = {
        int(row["buyback_id"])
        for row in copied
        if str(row.get("movement_type") or "") == "OTELLO_BUYBACK_DAILY"
        and row.get("buyback_id") is not None
    }

    buyback_cash = Decimal("0")
    bemobi_gross = Decimal("0")
    bemobi_withholding = Decimal("0")
    daily_rows = 0
    weekly_rows = 0
    weekly_superseded = 0
    cross_start_weekly_excluded = 0
    bemobi_receipt_rows = 0
    withholding_rows = 0

    for row in copied:
        movement_type = str(row.get("movement_type") or "")
        amount = Decimal(str(row.get("amount_nok") or "0"))
        description = str(row.get("description") or "")
        external_id = str(row.get("external_movement_id") or "")

        if movement_type == "OTELLO_BUYBACK_DAILY":
            buyback_cash += amount
            daily_rows += 1
            continue
        if movement_type == "OTELLO_BUYBACK":
            buyback_id = row.get("buyback_id")
            if buyback_id is not None and int(buyback_id) in daily_buyback_ids:
                weekly_superseded += 1
                continue
            match = _BUYBACK_PERIOD_RE.search(description)
            if match and match.group(1) <= start_date < str(row.get("movement_date")):
                cross_start_weekly_excluded += 1
                continue
            buyback_cash += amount
            weekly_rows += 1
            continue
        if movement_type in {"BEMOBI_DIVIDEND", "BEMOBI_JCP"}:
            bemobi_gross += amount
            bemobi_receipt_rows += 1
            continue
        if movement_type == "TAX" and (
            external_id.startswith("bemobi-withholding:")
            or description.lower().startswith("bemobi jcp withholding")
        ):
            bemobi_withholding += amount
            withholding_rows += 1

    return {
        "ready": True,
        "buyback_cash_nok": buyback_cash,
        "bemobi_gross_cash_nok": bemobi_gross,
        "bemobi_withholding_nok": bemobi_withholding,
        "bemobi_net_cash_nok": bemobi_gross + bemobi_withholding,
        "daily_buyback_rows": daily_rows,
        "weekly_buyback_rows": weekly_rows,
        "weekly_buyback_rows_superseded": weekly_superseded,
        "cross_start_weekly_excluded": cross_start_weekly_excluded,
        "bemobi_receipt_rows": bemobi_receipt_rows,
        "withholding_rows": withholding_rows,
    }


def _receivable(connection, day: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT associated_receivable_nok, receivable_quality
        FROM other_net_assets_daily_estimates
        WHERE estimate_date=? LIMIT 1
        """,
        (day,),
    ).fetchone()
    if row is None:
        return {"ready": False, "reason": "missing_bemobi_receivable", "date": day}
    return {
        "ready": True,
        "amount_nok": Decimal(str(row["associated_receivable_nok"] or "0")),
        "quality": row["receivable_quality"],
    }


def _build_change_attribution(
    start: dict[str, Any],
    current: dict[str, Any],
    requested_start: str,
    *,
    bemobi_market: dict[str, Any] | None = None,
    cash_breakdown: dict[str, Any] | None = None,
    start_receivable: dict[str, Any] | None = None,
    current_receivable: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start_shares = int(start.get("shares_outstanding") or 0)
    current_shares = int(current.get("shares_outstanding") or 0)
    if start_shares <= 0 or current_shares <= 0:
        return {
            "ready": False,
            "reason": "invalid_share_count",
            "requested_start": requested_start,
            "resolved_start": start.get("date"),
            "current_date": current.get("date"),
        }

    start_total_nok = Decimal(str(start["nav_total_mnok"])) * MILLION
    current_total_nok = Decimal(str(current["nav_total_mnok"])) * MILLION
    reciprocal_scale = (
        Decimal("1") / Decimal(start_shares)
        + Decimal("1") / Decimal(current_shares)
    ) / Decimal("2")

    drivers: list[dict[str, Any]] = []

    bemobi_delta = _composition_amount_nok(current, "bemobi") - _composition_amount_nok(start, "bemobi")
    if bemobi_market and bemobi_market.get("ready"):
        price_effect = Decimal(str(bemobi_market["price_effect_nok"]))
        fx_effect = Decimal(str(bemobi_market["fx_effect_nok"]))
        if abs(price_effect + fx_effect - bemobi_delta) <= ATTRIBUTION_TOLERANCE_NOK:
            drivers.extend(
                [
                    _driver(
                        key="bemobi_price",
                        label="Bemobi – aksjekurs",
                        amount_nok=price_effect,
                        per_share_scale=reciprocal_scale,
                        details={
                            "start_price_brl": _float(bemobi_market.get("start_price_brl")),
                            "current_price_brl": _float(bemobi_market.get("current_price_brl")),
                            "start_price_date": bemobi_market.get("start_price_date"),
                            "current_price_date": bemobi_market.get("current_price_date"),
                        },
                    ),
                    _driver(
                        key="bemobi_fx",
                        label="Bemobi – BRL/NOK",
                        amount_nok=fx_effect,
                        per_share_scale=reciprocal_scale,
                        details={
                            "start_brl_nok": _float(bemobi_market.get("start_brl_nok")),
                            "current_brl_nok": _float(bemobi_market.get("current_brl_nok")),
                            "start_fx_date": bemobi_market.get("start_fx_date"),
                            "current_fx_date": bemobi_market.get("current_fx_date"),
                        },
                    ),
                ]
            )
        else:
            bemobi_market = None
    if not bemobi_market or not bemobi_market.get("ready"):
        drivers.append(
            _driver(
                key="bemobi_market",
                label="Bemobi – markedsverdi",
                amount_nok=bemobi_delta,
                per_share_scale=reciprocal_scale,
                details={"attribution": "UNAVAILABLE"},
            )
        )

    cash_delta = _composition_amount_nok(current, "cash") - _composition_amount_nok(start, "cash")
    buyback_cash_nok = Decimal("0")
    bemobi_paid_nok = Decimal("0")
    if cash_breakdown and cash_breakdown.get("ready"):
        buyback_cash_nok = Decimal(str(cash_breakdown.get("buyback_cash_nok") or "0"))
        bemobi_paid_nok = Decimal(str(cash_breakdown.get("bemobi_net_cash_nok") or "0"))
        drivers.append(
            _driver(
                key="bemobi_paid",
                label="Bemobi – utbetalt utbytte/renter",
                amount_nok=bemobi_paid_nok,
                per_share_scale=reciprocal_scale,
                details={
                    "gross_mnok": _float(Decimal(str(cash_breakdown.get("bemobi_gross_cash_nok") or "0")) / MILLION),
                    "withholding_mnok": _float(Decimal(str(cash_breakdown.get("bemobi_withholding_nok") or "0")) / MILLION),
                    "net_mnok": _float(bemobi_paid_nok / MILLION),
                    "receipt_rows": int(cash_breakdown.get("bemobi_receipt_rows") or 0),
                    "withholding_rows": int(cash_breakdown.get("withholding_rows") or 0),
                },
            )
        )
        drivers.append(
            _driver(
                key="buyback_cash",
                label="Tilbakekjøp – kontantbruk",
                amount_nok=buyback_cash_nok,
                per_share_scale=reciprocal_scale,
                details={
                    "cash_mnok": _float(buyback_cash_nok / MILLION),
                    "daily_rows": int(cash_breakdown.get("daily_buyback_rows") or 0),
                    "weekly_rows": int(cash_breakdown.get("weekly_buyback_rows") or 0),
                    "weekly_rows_superseded": int(cash_breakdown.get("weekly_buyback_rows_superseded") or 0),
                    "cross_start_weekly_excluded": int(cash_breakdown.get("cross_start_weekly_excluded") or 0),
                },
            )
        )

    other_cash_delta = cash_delta - buyback_cash_nok - bemobi_paid_nok
    start_operating_cost_nok = Decimal(
        str(_composition_details(start, "cash").get("operating_cost_mnok") or "0")
    ) * MILLION
    current_operating_cost_nok = Decimal(
        str(_composition_details(current, "cash").get("operating_cost_mnok") or "0")
    ) * MILLION
    operating_cost_delta_nok = -(current_operating_cost_nok - start_operating_cost_nok)
    drivers.append(
        _driver(
            key="other_cash",
            label="Øvrig kontantendring",
            amount_nok=other_cash_delta,
            per_share_scale=reciprocal_scale,
            details={
                "start_amount_mnok": _float(_composition_amount_nok(start, "cash") / MILLION),
                "current_amount_mnok": _float(_composition_amount_nok(current, "cash") / MILLION),
                "operating_cost_mnok": _float(operating_cost_delta_nok / MILLION),
                "other_movements_mnok": _float(
                    (other_cash_delta - operating_cost_delta_nok) / MILLION
                ),
            },
        )
    )

    ona_delta = _composition_amount_nok(current, "ona") - _composition_amount_nok(start, "ona")
    receivable_change = Decimal("0")
    receivable_ready = bool(
        start_receivable
        and current_receivable
        and start_receivable.get("ready")
        and current_receivable.get("ready")
    )
    if receivable_ready:
        assert start_receivable and current_receivable
        start_receivable_nok = Decimal(str(start_receivable.get("amount_nok") or "0"))
        current_receivable_nok = Decimal(str(current_receivable.get("amount_nok") or "0"))
        receivable_change = current_receivable_nok - start_receivable_nok
        drivers.append(
            _driver(
                key="bemobi_receivable",
                label="Bemobi – tilgode utbytte/renter",
                amount_nok=receivable_change,
                per_share_scale=reciprocal_scale,
                details={
                    "start_mnok": _float(start_receivable_nok / MILLION),
                    "current_mnok": _float(current_receivable_nok / MILLION),
                    "start_quality": start_receivable.get("quality"),
                    "current_quality": current_receivable.get("quality"),
                },
            )
        )

    other_ona_delta = ona_delta - receivable_change
    drivers.append(
        _driver(
            key="other_ona",
            label="Øvrige nettoeiendeler",
            amount_nok=other_ona_delta,
            per_share_scale=reciprocal_scale,
            details={
                "start_amount_mnok": _float(_composition_amount_nok(start, "ona") / MILLION),
                "current_amount_mnok": _float(_composition_amount_nok(current, "ona") / MILLION),
                "bemobi_receivable_split": receivable_ready,
            },
        )
    )

    for key, label in (
        ("life360", "Life 360"),
        ("options", "Opsjoner – estimert kontantoppgjør"),
    ):
        before = _composition_amount_nok(start, key)
        after = _composition_amount_nok(current, key)
        drivers.append(
            _driver(
                key=key,
                label=label,
                amount_nok=after - before,
                per_share_scale=reciprocal_scale,
                details={
                    "start_amount_mnok": _float(before / MILLION),
                    "current_amount_mnok": _float(after / MILLION),
                },
            )
        )

    numerator_change = current_total_nok - start_total_nok
    attributed_numerator = sum(
        (
            Decimal(str(item["amount_mnok"])) * MILLION
            for item in drivers
            if item.get("amount_mnok") is not None
        ),
        Decimal("0"),
    )
    numerator_residual = numerator_change - attributed_numerator
    if abs(numerator_residual) > ATTRIBUTION_TOLERANCE_NOK:
        drivers.append(
            _driver(
                key="model_residual",
                label="Øvrig modell-/avstemmingsendring",
                amount_nok=numerator_residual,
                per_share_scale=reciprocal_scale,
                details={"reason": "composition_change_does_not_fully_reconcile"},
            )
        )

    drivers.append(
        _share_count_driver(
            start_total_nok=start_total_nok,
            current_total_nok=current_total_nok,
            start_shares=start_shares,
            current_shares=current_shares,
        )
    )

    total_change = Decimal(str(current["nav_per_share"])) - Decimal(str(start["nav_per_share"]))
    driver_total = sum(
        (Decimal(str(item.get("per_share_nok") or "0")) for item in drivers),
        Decimal("0"),
    )
    return {
        "ready": True,
        "requested_start": requested_start,
        "resolved_start": start["date"],
        "current_date": current["date"],
        "start_nav_per_share": start["nav_per_share"],
        "current_nav_per_share": current["nav_per_share"],
        "change_per_share_nok": _float(total_change),
        "drivers": drivers,
        "reconciliation_residual_nok": _float(total_change - driver_total),
        "attribution_method": "SYMMETRIC_VALUE_SHARECOUNT_SHAPLEY",
        "share_count_change": {
            "start_shares": start_shares,
            "current_shares": current_shares,
            "shares_reduced": start_shares - current_shares,
        },
    }


def _estimated_point(connection, day: str, database_path: str | None) -> dict[str, Any]:
    row = connection.execute(
        """SELECT substr(as_of_at,1,10) AS date, nav_total_nok, nav_per_share_nok, otec_price_nok,
                  bemobi_value_nok, cash_estimate_nok, other_net_assets_nok, shares_outstanding, components_json
           FROM nav_snapshots WHERE calculation_version=? AND nav_scope='FULL' AND substr(as_of_at,1,10)=?
           ORDER BY as_of_at DESC,id DESC LIMIT 1""",
        (FULL_CALCULATION_VERSION, day),
    ).fetchone()
    if row is None:
        return {"ready": False, "reason": "missing_full_nav_row", "date": day}
    row = dict(row)
    components = _components(row.get("components_json"))
    option_values = _option_values(components)
    settlement_inputs = settlement_inputs_from_components(components)
    if option_values is None or settlement_inputs is None:
        return {"ready": False, "reason": "missing_option_inputs", "date": day}
    accounting_option_nok, _ = option_values
    option_count, strike_nok = settlement_inputs
    anchor = connection.execute(
        "SELECT as_of_date FROM cash_anchors WHERE anchor_type='REPORTED' AND as_of_date<=? ORDER BY as_of_date DESC,id DESC LIMIT 1",
        (day,),
    ).fetchone()
    if anchor is None:
        return {"ready": False, "reason": "missing_reported_cash_anchor", "date": day}
    cash_anchor_date = str(anchor["as_of_date"])
    usd_nok = _nearest_fx(connection, "USD", day)
    base_cost = _latest_cost_anchors(connection, day).get("BASE")
    if usd_nok is None or base_cost is None:
        return {"ready": False, "reason": "missing_estimated_nav_anchor", "date": day}
    cash_fx = _cash_fx_revaluation(connection, cash_anchor_date=cash_anchor_date, as_of_date=day)
    if not cash_fx.get("ready"):
        return {"ready": False, "reason": cash_fx.get("reason") or "cash_fx_not_ready", "date": day}
    days_since_anchor = max(0, (date.fromisoformat(day) - date.fromisoformat(cash_anchor_date)).days)
    operating_cost_nok = (
        Decimal(str(base_cost["amount_usd_decimal"]))
        / Decimal(int(base_cost["period_days_int"]))
        * Decimal(days_since_anchor)
        * Decimal(str(usd_nok["rate"]))
    )
    cash_fx_nok = Decimal(str(cash_fx.get("adjustment_nok") or "0"))
    life360 = life360_nav_adjustment(as_of_date=day, database_path=database_path)
    life360_adjustment_nok = (
        Decimal(str(life360.get("adjustment_nok") or "0"))
        if life360.get("ready")
        else Decimal("0")
    )
    full_nav_total_nok = Decimal(str(row["nav_total_nok"]))
    bemobi_nok = Decimal(str(row.get("bemobi_value_nok") or "0"))
    reported_cash_nok = Decimal(str(row.get("cash_estimate_nok") or "0"))
    reported_ona_nok = Decimal(str(row.get("other_net_assets_nok") or "0"))
    shares = int(row["shares_outstanding"])
    if shares <= 0:
        return {"ready": False, "reason": "invalid_share_count", "date": day}
    cash_nok = reported_cash_nok + cash_fx_nok - operating_cost_nok
    ona_ex_option_nok = reported_ona_nok + accounting_option_nok
    pre_option_total_nok = (
        full_nav_total_nok
        + accounting_option_nok
        + cash_fx_nok
        + life360_adjustment_nok
        - operating_cost_nok
    )
    settlement = nav_cash_settlement(
        pre_option_total_nok=pre_option_total_nok,
        shares_outstanding=shares,
        option_count=option_count,
        strike_nok=strike_nok,
    )
    settlement_nok = Decimal(str(settlement["settlement_nok"]))
    estimated_total_nok = Decimal(str(settlement["economic_total_after_settlement_nok"]))
    estimated_per_share = Decimal(str(settlement["nav_after_option_per_share_nok"]))
    otec_price = Decimal(str(row["otec_price_nok"])) if row.get("otec_price_nok") is not None else None
    discount = (
        (Decimal("1") - otec_price / estimated_per_share) * Decimal("100")
        if otec_price is not None and estimated_per_share > 0
        else None
    )
    composition = [
        _component("bemobi", "Bemobi", bemobi_nok, shares, "Bemobi-aksjer × BMOB3-kurs × BRL/NOK"),
        _component(
            "cash",
            "Estimert kontantbeholdning",
            cash_nok,
            shares,
            "Rapportert kontantbeholdning + valutaeffekt − estimert drift siden rapport",
            {
                "reported_cash_mnok": _float(reported_cash_nok / MILLION),
                "cash_fx_adjustment_mnok": _float(cash_fx_nok / MILLION),
                "operating_cost_mnok": _float(operating_cost_nok / MILLION),
                "cash_anchor_date": cash_anchor_date,
            },
        ),
        _component(
            "ona",
            "Øvrige nettoeiendeler",
            ona_ex_option_nok,
            shares,
            "Regnskapsmessig ONA + regnskapsført opsjonsforpliktelse",
            {
                "reported_ona_mnok": _float(reported_ona_nok / MILLION),
                "accounting_option_liability_mnok": _float(accounting_option_nok / MILLION),
            },
        ),
        _component(
            "life360",
            "Life360 mark-to-market",
            life360_adjustment_nok,
            shares,
            "Dagens verdi av LIF − Life360-verdi innebygd i siste rapporterte ONA",
            {
                "active": bool(life360.get("ready")),
                "price_date": life360.get("price_date"),
                "anchor_date": life360.get("anchor_date"),
            },
        ),
        _component(
            "options",
            "Opsjoner – estimert kontantoppgjør",
            -settlement_nok,
            shares,
            "Selvkonsistent kontantoppgjør ved Estimert NAV",
            {
                "option_count": option_count,
                "strike_nok": _float(strike_nok),
                "settlement_mnok": _float(settlement_nok / MILLION),
            },
        ),
    ]
    composition_total = sum(
        (Decimal(str(item["amount_mnok"])) * MILLION for item in composition),
        Decimal("0"),
    )
    return {
        "ready": True,
        "date": day,
        "nav_total_mnok": _float(estimated_total_nok / MILLION),
        "nav_per_share": _float(estimated_per_share),
        "otec_price": _float(otec_price),
        "discount_pct": _float(discount),
        "shares_outstanding": shares,
        "accounting_nav_per_share": _float(row.get("nav_per_share_nok")),
        "composition": composition,
        "reconciliation_residual_mnok": _float((estimated_total_nok - composition_total) / MILLION),
        "model": "ESTIMATED_NAV_V1",
    }


def _change(
    start: dict[str, Any],
    current: dict[str, Any],
    requested_start: str,
    database_path: str | None,
) -> dict[str, Any]:
    start_date = str(start["date"])
    current_date = str(current["date"])
    with get_connection(database_path) as connection:
        bemobi_delta = _composition_amount_nok(current, "bemobi") - _composition_amount_nok(start, "bemobi")
        bemobi_market = _bemobi_market_attribution(
            connection,
            start_date=start_date,
            current_date=current_date,
            expected_change_nok=bemobi_delta,
        )
        cash_breakdown = _cash_breakdown(
            connection,
            start_date=start_date,
            current_date=current_date,
        )
        start_receivable = _receivable(connection, start_date)
        current_receivable = _receivable(connection, current_date)
    return _build_change_attribution(
        start,
        current,
        requested_start,
        bemobi_market=bemobi_market,
        cash_breakdown=cash_breakdown,
        start_receivable=start_receivable,
        current_receivable=current_receivable,
    )


def estimated_nav_history(
    database_path: str | None = None,
    *,
    days: int,
    year_to_date: bool = False,
) -> dict[str, Any]:
    days = max(30, min(int(days), 3650))
    with get_connection(database_path) as connection:
        latest = connection.execute(
            "SELECT MAX(substr(as_of_at,1,10)) AS max_date FROM nav_snapshots WHERE calculation_version=? AND nav_scope='FULL'",
            (FULL_CALCULATION_VERSION,),
        ).fetchone()
        current_date = latest["max_date"] if latest is not None else None
        if current_date is None:
            return {"ready": False, "reason": "missing_full_nav", "points": []}
        current_day = date.fromisoformat(str(current_date))
        requested_start = (
            date(current_day.year, 1, 1).isoformat()
            if year_to_date
            else (current_day - timedelta(days=days)).isoformat()
        )
        rows = connection.execute(
            "SELECT DISTINCT substr(as_of_at,1,10) AS date FROM nav_snapshots WHERE calculation_version=? AND nav_scope='FULL' AND substr(as_of_at,1,10)>=? AND substr(as_of_at,1,10)<=? ORDER BY date",
            (FULL_CALCULATION_VERSION, requested_start, current_date),
        ).fetchall()
        predecessor = connection.execute(
            "SELECT MAX(substr(as_of_at,1,10)) AS date FROM nav_snapshots WHERE calculation_version=? AND nav_scope='FULL' AND substr(as_of_at,1,10)<=?",
            (FULL_CALCULATION_VERSION, requested_start),
        ).fetchone()
        dates = [str(row["date"]) for row in rows if row["date"]]
        predecessor_date = predecessor["date"] if predecessor is not None else None
        if predecessor_date and predecessor_date not in dates:
            dates.insert(0, str(predecessor_date))
        if str(current_date) not in dates:
            dates.append(str(current_date))
        dates = _pick_dates(sorted(set(dates)))
        full_points, failures = [], []
        for day in dates:
            point = _estimated_point(connection, day, database_path)
            if point.get("ready"):
                full_points.append(point)
            else:
                failures.append({"date": day, "reason": point.get("reason")})
    if not full_points:
        return {
            "ready": False,
            "reason": "estimated_history_not_ready",
            "requested_start": requested_start,
            "current_date": current_date,
            "failures": failures[:10],
            "points": [],
        }
    current = next(
        (item for item in reversed(full_points) if item["date"] == current_date),
        full_points[-1],
    )
    start = min(
        full_points,
        key=lambda item: abs(
            (date.fromisoformat(item["date"]) - date.fromisoformat(requested_start)).days
        ),
    )
    public_points = [
        {
            "date": item["date"],
            "nav_per_share": item["nav_per_share"],
            "otec_price": item["otec_price"],
            "discount_pct": item["discount_pct"],
        }
        for item in full_points
    ]
    return {
        "ready": True,
        "model": "ESTIMATED_NAV_V1",
        "requested_start": requested_start,
        "from": public_points[0]["date"],
        "to": public_points[-1]["date"],
        "point_count": len(public_points),
        "points": public_points,
        "current": current,
        "change": _change(start, current, requested_start, database_path),
        "failures": failures[:10],
        "note": (
            "Estimert NAV bruker samme kildebelagte investorlogikk historisk som i dagens "
            "Estimert NAV. Manglende historiske innganger gjettes ikke. Endringsbroen "
            "skiller Bemobi-kurs, BRL/NOK, utbyttefordring og utbetalt utbytte/renter, samt "
            "tilbakekjøpenes kontantbruk og aksjereduksjon."
        ),
    }
