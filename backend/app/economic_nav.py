from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.nav.daily_nav import CALCULATION_VERSION as CORE_CALCULATION_VERSION
from app.nav.full_nav import FULL_CALCULATION_VERSION

MAX_FX_LOOKBACK_DAYS = 7
MILLION = Decimal("1000000")
CASH_BRIDGE_TOLERANCE_NOK = Decimal("1000")


def _float(value: Decimal | str | int | float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def _discount_pct(otec_price: Decimal | None, nav_per_share: Decimal) -> Decimal | None:
    if otec_price is None or nav_per_share <= 0:
        return None
    return (Decimal("1") - otec_price / nav_per_share) * Decimal("100")


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _option_values(components: dict[str, Any]) -> tuple[Decimal, Decimal] | None:
    option = (components.get("other_net_assets") or {}).get("option_liability") or {}
    accounting_raw = option.get("amount_nok")
    inputs = option.get("inputs") or {}
    gross_raw = inputs.get("gross_fair_value_nok")
    if gross_raw is None:
        fair_value_raw = option.get("fair_value_per_option_nok")
        option_count_raw = inputs.get("option_count")
        if fair_value_raw is not None and option_count_raw is not None:
            gross_raw = Decimal(str(fair_value_raw)) * Decimal(str(option_count_raw))
    if accounting_raw is None or gross_raw is None:
        return None
    return Decimal(str(accounting_raw)), Decimal(str(gross_raw))


def _nearest_fx(connection, base: str, day: str):
    floor_date = (
        date.fromisoformat(day) - timedelta(days=MAX_FX_LOOKBACK_DAYS)
    ).isoformat()
    return connection.execute(
        """
        SELECT id, substr(observed_at,1,10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency=? AND quote_currency='NOK'
          AND substr(observed_at,1,10) <= ? AND substr(observed_at,1,10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (base, day, floor_date),
    ).fetchone()


def _latest_cost_anchors(connection, as_of_date: str) -> dict[str, dict[str, Any]]:
    rows = connection.execute("""
        SELECT id, published_at, metadata_json
        FROM source_documents
        WHERE document_type='ECONOMIC_NAV_COST_ANCHOR'
        ORDER BY published_at DESC, id DESC
        """).fetchall()
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        scenario = str(metadata.get("scenario") or "").upper()
        effective_from = str(metadata.get("effective_from") or "")[:10]
        if scenario not in {"BASE", "CONSERVATIVE"} or not effective_from:
            continue
        if effective_from > as_of_date or scenario in selected:
            continue
        try:
            amount = Decimal(str(metadata["amount_usd"]))
            period_days = int(metadata["period_days"])
        except (KeyError, TypeError, ValueError):
            continue
        if amount < 0 or period_days <= 0:
            continue
        selected[scenario] = {
            **metadata,
            "source_document_id": int(row["id"]),
            "amount_usd_decimal": amount,
            "period_days_int": period_days,
        }
    return selected


def _cash_fx_anchor(connection, cash_anchor_date: str) -> dict[str, Any] | None:
    rows = connection.execute("""
        SELECT id, metadata_json
        FROM source_documents
        WHERE document_type='ECONOMIC_NAV_CASH_FX_ANCHOR'
        ORDER BY published_at DESC, id DESC
        """).fetchall()
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        if str(metadata.get("as_of_date") or "")[:10] == cash_anchor_date:
            return {**metadata, "source_document_id": int(row["id"])}
    return None


def _cash_fx_revaluation(
    connection, *, cash_anchor_date: str, as_of_date: str
) -> dict[str, Any]:
    anchor = _cash_fx_anchor(connection, cash_anchor_date)
    if anchor is None:
        return {
            "ready": True,
            "adjustment_nok": Decimal("0"),
            "details": {
                "quality": "UNAVAILABLE_FOR_CURRENT_CASH_ANCHOR",
                "anchor_date": cash_anchor_date,
                "adjustment_mnok": 0.0,
                "note": "No source-backed currency allocation exists for the current reported cash anchor; no FX revaluation is guessed.",
            },
        }

    anchor_usd = _nearest_fx(connection, "USD", cash_anchor_date)
    anchor_brl = _nearest_fx(connection, "BRL", cash_anchor_date)
    current_usd = _nearest_fx(connection, "USD", as_of_date)
    current_brl = _nearest_fx(connection, "BRL", as_of_date)
    if any(item is None for item in (anchor_usd, anchor_brl, current_usd, current_brl)):
        return {
            "ready": False,
            "reason": "missing_cash_fx_revaluation_rates",
            "anchor_date": cash_anchor_date,
        }

    anchor_usd_nok = Decimal(str(anchor_usd["rate"]))
    anchor_brl_nok = Decimal(str(anchor_brl["rate"]))
    current_usd_nok = Decimal(str(current_usd["rate"]))
    current_brl_nok = Decimal(str(current_brl["rate"]))
    if anchor_brl_nok <= 0:
        return {"ready": False, "reason": "invalid_anchor_brl_nok"}

    exposures = anchor.get("exposures")
    if not isinstance(exposures, list) or not exposures:
        return {"ready": False, "reason": "invalid_cash_fx_exposure_anchor"}

    adjustment = Decimal("0")
    total_usd_equivalent = Decimal("0")
    source_backed_usd_equivalent = Decimal("0")
    components: list[dict[str, Any]] = []
    for item in exposures:
        if not isinstance(item, dict):
            return {"ready": False, "reason": "invalid_cash_fx_exposure_component"}
        currency = str(item.get("currency") or "").upper()
        try:
            usd_equivalent = Decimal(str(item["usd_equivalent"]))
        except (KeyError, TypeError, ValueError):
            return {"ready": False, "reason": "invalid_cash_fx_exposure_amount"}
        if usd_equivalent < 0 or currency not in {"NOK", "USD", "BRL", "UNALLOCATED"}:
            return {"ready": False, "reason": "invalid_cash_fx_exposure_component"}

        anchor_value_nok = usd_equivalent * anchor_usd_nok
        original_amount: Decimal | None = None
        current_value_nok = anchor_value_nok
        if currency == "USD":
            source_backed_usd_equivalent += usd_equivalent
            original_amount = usd_equivalent
            current_value_nok = original_amount * current_usd_nok
        elif currency == "BRL":
            source_backed_usd_equivalent += usd_equivalent
            original_amount = anchor_value_nok / anchor_brl_nok
            current_value_nok = original_amount * current_brl_nok
        elif currency == "NOK":
            source_backed_usd_equivalent += usd_equivalent
            original_amount = anchor_value_nok
            current_value_nok = original_amount

        component_adjustment = current_value_nok - anchor_value_nok
        adjustment += component_adjustment
        total_usd_equivalent += usd_equivalent
        components.append(
            {
                "currency": currency,
                "usd_equivalent_at_anchor": _float(usd_equivalent),
                "original_currency_amount": _float(original_amount),
                "anchor_value_mnok": _float(anchor_value_nok / Decimal("1000000")),
                "current_value_mnok": _float(current_value_nok / Decimal("1000000")),
                "adjustment_mnok": _float(component_adjustment / Decimal("1000000")),
                "quality": item.get("quality"),
                "notes": item.get("notes"),
            }
        )

    declared_total = Decimal(str(anchor.get("total_cash_usd") or total_usd_equivalent))
    if total_usd_equivalent != declared_total:
        return {
            "ready": False,
            "reason": "cash_fx_exposure_does_not_reconcile",
            "exposure_total_usd": _float(total_usd_equivalent),
            "declared_total_usd": _float(declared_total),
        }

    coverage_pct = (
        source_backed_usd_equivalent / total_usd_equivalent * Decimal("100")
        if total_usd_equivalent > 0
        else Decimal("0")
    )
    return {
        "ready": True,
        "adjustment_nok": adjustment,
        "details": {
            "quality": (
                "FULL_EXPOSURE_REVALUATION"
                if source_backed_usd_equivalent == total_usd_equivalent
                else "PARTIAL_EXPOSURE_REVALUATION"
            ),
            "anchor_date": cash_anchor_date,
            "source_document_id": anchor.get("source_document_id"),
            "allocation_quality": anchor.get("allocation_quality"),
            "coverage_pct": _float(coverage_pct),
            "adjustment_mnok": _float(adjustment / Decimal("1000000")),
            "anchor_usd_nok": _float(anchor_usd_nok),
            "anchor_usd_nok_date": anchor_usd["rate_date"],
            "anchor_brl_nok": _float(anchor_brl_nok),
            "anchor_brl_nok_date": anchor_brl["rate_date"],
            "current_usd_nok": _float(current_usd_nok),
            "current_usd_nok_date": current_usd["rate_date"],
            "current_brl_nok": _float(current_brl_nok),
            "current_brl_nok_date": current_brl["rate_date"],
            "components": components,
            "policy": anchor.get("policy")
            or "REVALUE_SOURCE_BACKED_USD_BRL_KEEP_NOK_FIXED_KEEP_UNALLOCATED_FIXED",
            "note": anchor.get("notes"),
        },
    }


def build_cash_bridge(
    *,
    anchor_date: str,
    reported_cash_nok: Decimal,
    modeled_cash_nok: Decimal,
    shares_outstanding: int,
    buyback_cash_nok: Decimal = Decimal("0"),
    bemobi_cash_nok: Decimal = Decimal("0"),
    patent_proceeds_nok: Decimal = Decimal("0"),
    operating_cost_nok: Decimal = Decimal("0"),
    cash_fx_nok: Decimal = Decimal("0"),
) -> dict[str, Any]:
    """Build a compact bridge that reconciles reported and economic cash."""
    identified_modeled_cash = buyback_cash_nok + bemobi_cash_nok + patent_proceeds_nok
    other_cash_nok = modeled_cash_nok - reported_cash_nok - identified_modeled_cash
    estimated_cash_nok = modeled_cash_nok + cash_fx_nok - operating_cost_nok
    movements = [
        ("bemobi_payments", "Bemobi-utbetalinger", bemobi_cash_nok),
        ("patent_proceeds", "Patentoppgjør", patent_proceeds_nok),
        ("buybacks", "Tilbakekjøp", buyback_cash_nok),
        ("operating_costs", "Estimert drift", -operating_cost_nok),
        ("cash_fx", "Valutaeffekt", cash_fx_nok),
        ("other_cash", "Andre kontantbevegelser", other_cash_nok),
    ]
    visible_movements = [
        {"key": key, "label": label, "amount_mnok": _float(amount / MILLION)}
        for key, label, amount in movements
        if abs(amount) > CASH_BRIDGE_TOLERANCE_NOK
    ]
    change_nok = estimated_cash_nok - reported_cash_nok
    visible_total = sum(
        (Decimal(str(item["amount_mnok"])) * MILLION for item in visible_movements),
        Decimal("0"),
    )
    return {
        "report_date": anchor_date,
        "reported_cash_mnok": _float(reported_cash_nok / MILLION),
        "estimated_cash_mnok": _float(estimated_cash_nok / MILLION),
        "cash_per_share_nok": (
            _float(estimated_cash_nok / Decimal(shares_outstanding))
            if shares_outstanding > 0
            else None
        ),
        "movements": visible_movements,
        "change_since_report_mnok": _float(change_nok / MILLION),
        "reconciles": abs(visible_total - change_nok) <= CASH_BRIDGE_TOLERANCE_NOK,
        "tolerance_nok": _float(CASH_BRIDGE_TOLERANCE_NOK),
    }


def build_economic_nav_overlay(
    *,
    as_of_date: str,
    cash_anchor_date: str,
    usd_nok: Decimal,
    usd_nok_date: str,
    nav_total_nok: Decimal,
    nav_per_share_nok: Decimal,
    otec_price_nok: Decimal | None,
    cash_estimate_nok: Decimal,
    shares_outstanding: int,
    accounting_option_liability_nok: Decimal,
    economic_option_value_nok: Decimal,
    base_operating_cost_usd: Decimal,
    base_operating_cost_period_days: int,
    conservative_operating_cost_usd: Decimal,
    conservative_operating_cost_period_days: int,
    base_cost_metadata: dict[str, Any] | None = None,
    conservative_cost_metadata: dict[str, Any] | None = None,
    cash_fx_adjustment_nok: Decimal = Decimal("0"),
    cash_fx_details: dict[str, Any] | None = None,
    reported_cash_nok: Decimal | None = None,
    cash_bridge_movements: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    current = date.fromisoformat(as_of_date)
    anchor = date.fromisoformat(cash_anchor_date)
    days_since_anchor = max(0, (current - anchor).days)

    base_daily_usd = base_operating_cost_usd / Decimal(base_operating_cost_period_days)
    conservative_daily_usd = conservative_operating_cost_usd / Decimal(
        conservative_operating_cost_period_days
    )
    base_cost_usd = base_daily_usd * Decimal(days_since_anchor)
    conservative_cost_usd = conservative_daily_usd * Decimal(days_since_anchor)
    base_cost_nok = base_cost_usd * usd_nok
    conservative_cost_nok = conservative_cost_usd * usd_nok

    option_overhang_nok = max(
        Decimal("0"), economic_option_value_nok - accounting_option_liability_nok
    )
    economic_total_nok = (
        nav_total_nok + cash_fx_adjustment_nok - option_overhang_nok - base_cost_nok
    )
    conservative_total_nok = (
        nav_total_nok
        + cash_fx_adjustment_nok
        - option_overhang_nok
        - conservative_cost_nok
    )
    share_count = Decimal(shares_outstanding)
    economic_per_share = economic_total_nok / share_count
    conservative_per_share = conservative_total_nok / share_count
    economic_cash_nok = cash_estimate_nok + cash_fx_adjustment_nok - base_cost_nok
    base_meta = base_cost_metadata or {}
    conservative_meta = conservative_cost_metadata or {}

    result = {
        "ready": True,
        "as_of_date": as_of_date,
        "quality": "ESTIMATED_OVERLAY",
        "accounting_nav_per_share": _float(nav_per_share_nok),
        "nav_per_share": _float(economic_per_share),
        "discount_pct": _float(_discount_pct(otec_price_nok, economic_per_share)),
        "conservative_nav_per_share": _float(conservative_per_share),
        "conservative_discount_pct": _float(
            _discount_pct(otec_price_nok, conservative_per_share)
        ),
        "economic_cash_mnok": _float(economic_cash_nok / Decimal("1000000")),
        "cash_fx": cash_fx_details
        or {
            "quality": "NOT_APPLIED",
            "anchor_date": cash_anchor_date,
            "adjustment_mnok": _float(cash_fx_adjustment_nok / Decimal("1000000")),
        },
        "option": {
            "accounting_liability_mnok": _float(
                accounting_option_liability_nok / Decimal("1000000")
            ),
            "economic_value_mnok": _float(
                economic_option_value_nok / Decimal("1000000")
            ),
            "unrecognized_overhang_mnok": _float(
                option_overhang_nok / Decimal("1000000")
            ),
            "method": "full-black-scholes-gross-value-v1",
        },
        "operating_costs": {
            "anchor_date": cash_anchor_date,
            "days_since_anchor": days_since_anchor,
            "base_mnok": _float(base_cost_nok / Decimal("1000000")),
            "conservative_mnok": _float(conservative_cost_nok / Decimal("1000000")),
            "base_annualized_usd_m": _float(
                base_daily_usd * Decimal("365") / Decimal("1000000")
            ),
            "conservative_annualized_usd_m": _float(
                conservative_daily_usd * Decimal("365") / Decimal("1000000")
            ),
            "usd_nok": _float(usd_nok),
            "usd_nok_date": usd_nok_date,
            "method": "source-backed-operating-cost-anchor-v3",
            "source_period": base_meta.get("source_period"),
            "source_operating_cost_usd_m": _float(
                base_operating_cost_usd / Decimal("1000000")
            ),
            "source_measure": base_meta.get("source_measure"),
            "source_document_id": base_meta.get("source_document_id"),
            "source_effective_from": base_meta.get("effective_from"),
            "conservative_source_period": conservative_meta.get("source_period"),
            "conservative_operating_cost_usd_m": _float(
                conservative_operating_cost_usd / Decimal("1000000")
            ),
            "conservative_source_measure": conservative_meta.get("source_measure"),
            "conservative_source_document_id": conservative_meta.get(
                "source_document_id"
            ),
            "conservative_source_effective_from": conservative_meta.get(
                "effective_from"
            ),
            "interest_income_included": False,
        },
        "note": (
            "Economic NAV leaves validated accounting FULL NAV unchanged, revalues source-backed "
            "USD/BRL cash exposure, keeps source-backed NOK cash fixed in NOK, deducts the Black-Scholes "
            "option value not already recognized, and deducts source-backed post-anchor operating-cost "
            "run-rates. Any genuinely unallocated currency exposure remains fixed at anchor NOK value; "
            "interest income is not accrued."
        ),
    }
    if reported_cash_nok is not None:
        bridge = cash_bridge_movements or {}
        result["cash_bridge"] = build_cash_bridge(
            anchor_date=cash_anchor_date,
            reported_cash_nok=reported_cash_nok,
            modeled_cash_nok=cash_estimate_nok,
            shares_outstanding=shares_outstanding,
            buyback_cash_nok=bridge.get("buyback_cash_nok", Decimal("0")),
            bemobi_cash_nok=bridge.get("bemobi_cash_nok", Decimal("0")),
            patent_proceeds_nok=bridge.get("patent_proceeds_nok", Decimal("0")),
            operating_cost_nok=base_cost_nok,
            cash_fx_nok=cash_fx_adjustment_nok,
        )
    return result


def economic_nav_summary(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        dates = connection.execute(
            """
            SELECT
              MAX(CASE WHEN calculation_version=? AND nav_scope='CORE'
                       THEN substr(as_of_at,1,10) END) AS core_date,
              MAX(CASE WHEN calculation_version=? AND nav_scope='FULL'
                       THEN substr(as_of_at,1,10) END) AS full_date
            FROM nav_snapshots
            """,
            (CORE_CALCULATION_VERSION, FULL_CALCULATION_VERSION),
        ).fetchone()
        core_date = dates["core_date"] if dates is not None else None
        full_date = dates["full_date"] if dates is not None else None
        if full_date is None:
            return {"ready": False, "reason": "missing_full_nav"}
        if core_date != full_date:
            return {
                "ready": False,
                "reason": "full_nav_not_current",
                "core_date": core_date,
                "full_date": full_date,
            }

        row = connection.execute(
            """
            SELECT as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                   discount_pct, cash_estimate_nok, shares_outstanding,
                   components_json, status
            FROM nav_snapshots
            WHERE calculation_version=? AND nav_scope='FULL'
              AND substr(as_of_at,1,10)=?
            ORDER BY as_of_at DESC, id DESC LIMIT 1
            """,
            (FULL_CALCULATION_VERSION, full_date),
        ).fetchone()
        if row is None:
            return {"ready": False, "reason": "missing_full_nav_row"}

        try:
            components = json.loads(row["components_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return {"ready": False, "reason": "invalid_full_components"}
        option_values = _option_values(components)
        if option_values is None:
            return {"ready": False, "reason": "missing_option_economic_value"}
        accounting_option, economic_option = option_values

        anchor = connection.execute(
            """
            SELECT as_of_date, amount_nok, reported_amount, reported_currency
            FROM cash_anchors
            WHERE anchor_type='REPORTED' AND as_of_date <= ?
            ORDER BY as_of_date DESC, id DESC LIMIT 1
            """,
            (full_date,),
        ).fetchone()
        if anchor is None:
            return {"ready": False, "reason": "missing_reported_cash_anchor"}
        cash_anchor_date = str(anchor["as_of_date"])
        reported_amount = anchor["reported_amount"]
        reported_currency = str(anchor["reported_currency"] or "NOK")
        if reported_amount is not None:
            anchor_fx = (
                None
                if reported_currency == "NOK"
                else _nearest_fx(connection, reported_currency, cash_anchor_date)
            )
            if reported_currency != "NOK" and anchor_fx is None:
                return {"ready": False, "reason": "missing_reported_cash_fx"}
            reported_cash_nok = Decimal(str(reported_amount)) * (
                Decimal("1") if anchor_fx is None else Decimal(str(anchor_fx["rate"]))
            )
        elif anchor["amount_nok"] is not None:
            reported_cash_nok = Decimal(str(anchor["amount_nok"]))
        else:
            return {"ready": False, "reason": "missing_reported_cash_value"}

        from app.estimated_nav_history import _cash_breakdown

        movement_breakdown = _cash_breakdown(
            connection, start_date=cash_anchor_date, current_date=full_date
        )
        patent_rows = connection.execute(
            """
            SELECT amount_nok FROM cash_movements
            WHERE movement_date > ? AND movement_date <= ?
              AND identified_type='PATENT_PROCEEDS' AND confidence='CONFIRMED'
            """,
            (cash_anchor_date, full_date),
        ).fetchall()
        cash_bridge_movements = {
            "buyback_cash_nok": Decimal(str(movement_breakdown["buyback_cash_nok"])),
            "bemobi_cash_nok": Decimal(str(movement_breakdown["bemobi_net_cash_nok"])),
            "patent_proceeds_nok": sum(
                (Decimal(str(item["amount_nok"])) for item in patent_rows),
                Decimal("0"),
            ),
        }

        fx = _nearest_fx(connection, "USD", full_date)
        if fx is None:
            return {"ready": False, "reason": "missing_recent_usd_nok"}

        cost_anchors = _latest_cost_anchors(connection, full_date)
        base_cost = cost_anchors.get("BASE")
        conservative_cost = cost_anchors.get("CONSERVATIVE")
        if base_cost is None or conservative_cost is None:
            return {
                "ready": False,
                "reason": "missing_operating_cost_anchors",
                "available_scenarios": sorted(cost_anchors),
            }

        cash_fx = _cash_fx_revaluation(
            connection,
            cash_anchor_date=cash_anchor_date,
            as_of_date=full_date,
        )
        if not cash_fx.get("ready"):
            return cash_fx

        return build_economic_nav_overlay(
            as_of_date=full_date,
            cash_anchor_date=cash_anchor_date,
            usd_nok=Decimal(str(fx["rate"])),
            usd_nok_date=str(fx["rate_date"]),
            nav_total_nok=Decimal(str(row["nav_total_nok"])),
            nav_per_share_nok=Decimal(str(row["nav_per_share_nok"])),
            otec_price_nok=(
                Decimal(str(row["otec_price_nok"]))
                if row["otec_price_nok"] is not None
                else None
            ),
            cash_estimate_nok=Decimal(str(row["cash_estimate_nok"])),
            shares_outstanding=int(row["shares_outstanding"]),
            accounting_option_liability_nok=accounting_option,
            economic_option_value_nok=economic_option,
            base_operating_cost_usd=base_cost["amount_usd_decimal"],
            base_operating_cost_period_days=base_cost["period_days_int"],
            conservative_operating_cost_usd=conservative_cost["amount_usd_decimal"],
            conservative_operating_cost_period_days=conservative_cost[
                "period_days_int"
            ],
            base_cost_metadata=base_cost,
            conservative_cost_metadata=conservative_cost,
            cash_fx_adjustment_nok=cash_fx["adjustment_nok"],
            cash_fx_details=cash_fx["details"],
            reported_cash_nok=reported_cash_nok,
            cash_bridge_movements=cash_bridge_movements,
        )
