from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

CORE_CALCULATION_VERSION = "core-market-nav-daily-v1"
FULL_CALCULATION_VERSION = "full-market-nav-daily-v2"
MAX_FX_LOOKBACK_DAYS = 7


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


async def _nearest_fx(repository, base: str, day: str):
    floor_date = (date.fromisoformat(day) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT id, substr(observed_at,1,10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency=? AND quote_currency='NOK'
          AND substr(observed_at,1,10) <= ? AND substr(observed_at,1,10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (base, day, floor_date),
    )


async def _latest_cost_anchors(repository, as_of_date: str) -> dict[str, dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT id, published_at, metadata_json
        FROM source_documents
        WHERE document_type='ECONOMIC_NAV_COST_ANCHOR'
        ORDER BY published_at DESC, id DESC
        """
    )
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = _metadata(row.get("metadata_json"))
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


async def _cash_fx_anchor(repository, cash_anchor_date: str) -> dict[str, Any] | None:
    rows = await repository.all(
        """
        SELECT id, metadata_json
        FROM source_documents
        WHERE document_type='ECONOMIC_NAV_CASH_FX_ANCHOR'
        ORDER BY published_at DESC, id DESC
        """
    )
    for row in rows:
        metadata = _metadata(row.get("metadata_json"))
        if str(metadata.get("as_of_date") or "")[:10] == cash_anchor_date:
            return {**metadata, "source_document_id": int(row["id"])}
    return None


async def _cash_fx_revaluation(repository, *, cash_anchor_date: str, as_of_date: str) -> dict[str, Any]:
    anchor = await _cash_fx_anchor(repository, cash_anchor_date)
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

    anchor_usd = await _nearest_fx(repository, "USD", cash_anchor_date)
    anchor_brl = await _nearest_fx(repository, "BRL", cash_anchor_date)
    current_usd = await _nearest_fx(repository, "USD", as_of_date)
    current_brl = await _nearest_fx(repository, "BRL", as_of_date)
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
) -> dict[str, Any]:
    current = date.fromisoformat(as_of_date)
    anchor = date.fromisoformat(cash_anchor_date)
    days_since_anchor = max(0, (current - anchor).days)

    base_daily_usd = base_operating_cost_usd / Decimal(base_operating_cost_period_days)
    conservative_daily_usd = (
        conservative_operating_cost_usd / Decimal(conservative_operating_cost_period_days)
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

    return {
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
            "economic_value_mnok": _float(economic_option_value_nok / Decimal("1000000")),
            "unrecognized_overhang_mnok": _float(option_overhang_nok / Decimal("1000000")),
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
            "conservative_source_document_id": conservative_meta.get("source_document_id"),
            "conservative_source_effective_from": conservative_meta.get("effective_from"),
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


async def economic_nav_summary(repository) -> dict[str, Any]:
    dates = await repository.first(
        """
        SELECT
          MAX(CASE WHEN calculation_version=? AND nav_scope='CORE' THEN substr(as_of_at,1,10) END) AS core_date,
          MAX(CASE WHEN calculation_version=? AND nav_scope='FULL' THEN substr(as_of_at,1,10) END) AS full_date
        FROM nav_snapshots
        """,
        (CORE_CALCULATION_VERSION, FULL_CALCULATION_VERSION),
    )
    core_date = dates.get("core_date") if dates is not None else None
    full_date = dates.get("full_date") if dates is not None else None
    if full_date is None:
        return {"ready": False, "reason": "missing_full_nav"}
    if core_date != full_date:
        return {
            "ready": False,
            "reason": "full_nav_not_current",
            "core_date": core_date,
            "full_date": full_date,
        }

    row = await repository.first(
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
    )
    if row is None:
        return {"ready": False, "reason": "missing_full_nav_row"}

    try:
        components = json.loads(row.get("components_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {"ready": False, "reason": "invalid_full_components"}
    option_values = _option_values(components)
    if option_values is None:
        return {"ready": False, "reason": "missing_option_economic_value"}
    accounting_option, economic_option = option_values

    anchor = await repository.first(
        """
        SELECT as_of_date FROM cash_anchors
        WHERE anchor_type='REPORTED' AND as_of_date <= ?
        ORDER BY as_of_date DESC, id DESC LIMIT 1
        """,
        (full_date,),
    )
    if anchor is None:
        return {"ready": False, "reason": "missing_reported_cash_anchor"}
    cash_anchor_date = str(anchor["as_of_date"])

    fx = await _nearest_fx(repository, "USD", str(full_date))
    if fx is None:
        return {"ready": False, "reason": "missing_recent_usd_nok"}

    cost_anchors = await _latest_cost_anchors(repository, str(full_date))
    base_cost = cost_anchors.get("BASE")
    conservative_cost = cost_anchors.get("CONSERVATIVE")
    if base_cost is None or conservative_cost is None:
        return {
            "ready": False,
            "reason": "missing_operating_cost_anchors",
            "available_scenarios": sorted(cost_anchors),
        }

    cash_fx = await _cash_fx_revaluation(
        repository,
        cash_anchor_date=cash_anchor_date,
        as_of_date=str(full_date),
    )
    if not cash_fx.get("ready"):
        return cash_fx

    return build_economic_nav_overlay(
        as_of_date=str(full_date),
        cash_anchor_date=cash_anchor_date,
        usd_nok=Decimal(str(fx["rate"])),
        usd_nok_date=str(fx["rate_date"]),
        nav_total_nok=Decimal(str(row["nav_total_nok"])),
        nav_per_share_nok=Decimal(str(row["nav_per_share_nok"])),
        otec_price_nok=(
            Decimal(str(row["otec_price_nok"])) if row.get("otec_price_nok") is not None else None
        ),
        cash_estimate_nok=Decimal(str(row["cash_estimate_nok"])),
        shares_outstanding=int(row["shares_outstanding"]),
        accounting_option_liability_nok=accounting_option,
        economic_option_value_nok=economic_option,
        base_operating_cost_usd=base_cost["amount_usd_decimal"],
        base_operating_cost_period_days=base_cost["period_days_int"],
        conservative_operating_cost_usd=conservative_cost["amount_usd_decimal"],
        conservative_operating_cost_period_days=conservative_cost["period_days_int"],
        base_cost_metadata=base_cost,
        conservative_cost_metadata=conservative_cost,
        cash_fx_adjustment_nok=cash_fx["adjustment_nok"],
        cash_fx_details=cash_fx["details"],
    )
