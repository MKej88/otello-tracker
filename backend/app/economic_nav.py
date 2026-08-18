from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.nav.daily_nav import CALCULATION_VERSION as CORE_CALCULATION_VERSION
from app.nav.full_nav import FULL_CALCULATION_VERSION

MAX_FX_LOOKBACK_DAYS = 7
BASE_OPERATING_COST_USD = Decimal("1022000")
BASE_OPERATING_COST_PERIOD_DAYS = Decimal("184")
CONSERVATIVE_OPERATING_COST_USD = Decimal("2308000")
CONSERVATIVE_OPERATING_COST_PERIOD_DAYS = Decimal("365")


def _float(value: Decimal | str | int | float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def _discount_pct(otec_price: Decimal | None, nav_per_share: Decimal) -> Decimal | None:
    if otec_price is None or nav_per_share <= 0:
        return None
    return (Decimal("1") - otec_price / nav_per_share) * Decimal("100")


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
) -> dict[str, Any]:
    current = date.fromisoformat(as_of_date)
    anchor = date.fromisoformat(cash_anchor_date)
    days_since_anchor = max(0, (current - anchor).days)

    base_daily_usd = BASE_OPERATING_COST_USD / BASE_OPERATING_COST_PERIOD_DAYS
    conservative_daily_usd = (
        CONSERVATIVE_OPERATING_COST_USD / CONSERVATIVE_OPERATING_COST_PERIOD_DAYS
    )
    base_cost_usd = base_daily_usd * Decimal(days_since_anchor)
    conservative_cost_usd = conservative_daily_usd * Decimal(days_since_anchor)
    base_cost_nok = base_cost_usd * usd_nok
    conservative_cost_nok = conservative_cost_usd * usd_nok

    option_overhang_nok = max(
        Decimal("0"), economic_option_value_nok - accounting_option_liability_nok
    )
    economic_total_nok = nav_total_nok - option_overhang_nok - base_cost_nok
    conservative_total_nok = nav_total_nok - option_overhang_nok - conservative_cost_nok
    share_count = Decimal(shares_outstanding)
    economic_per_share = economic_total_nok / share_count
    conservative_per_share = conservative_total_nok / share_count
    economic_cash_nok = cash_estimate_nok - base_cost_nok

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
            "method": "latest-half-adjusted-ebitda-run-rate-v1",
            "source_period": "2H25",
            "source_adjusted_ebitda_usd_m": 1.022,
            "conservative_source_period": "FY25",
            "conservative_adjusted_ebitda_usd_m": 2.308,
            "interest_income_included": False,
        },
        "note": (
            "Economic NAV leaves the validated accounting FULL NAV unchanged, then deducts "
            "the Black-Scholes option value not already recognized in the accounting liability "
            "and an estimated post-anchor operating-cost run-rate. The base cost proxy uses "
            "2H25 adjusted EBITDA burn; the conservative sensitivity uses FY25 adjusted EBITDA burn. "
            "Interest income is not accrued, making the overlay intentionally conservative."
        ),
    }


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
            SELECT as_of_date FROM cash_anchors
            WHERE anchor_type='REPORTED' AND as_of_date <= ?
            ORDER BY as_of_date DESC, id DESC LIMIT 1
            """,
            (full_date,),
        ).fetchone()
        if anchor is None:
            return {"ready": False, "reason": "missing_reported_cash_anchor"}

        floor_date = (date.fromisoformat(full_date) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
        fx = connection.execute(
            """
            SELECT substr(observed_at,1,10) AS rate_date, rate
            FROM fx_rates
            WHERE base_currency='USD' AND quote_currency='NOK'
              AND substr(observed_at,1,10) <= ? AND substr(observed_at,1,10) >= ?
            ORDER BY observed_at DESC, id DESC LIMIT 1
            """,
            (full_date, floor_date),
        ).fetchone()
        if fx is None:
            return {"ready": False, "reason": "missing_recent_usd_nok"}

        return build_economic_nav_overlay(
            as_of_date=full_date,
            cash_anchor_date=str(anchor["as_of_date"]),
            usd_nok=Decimal(str(fx["rate"])),
            usd_nok_date=str(fx["rate_date"]),
            nav_total_nok=Decimal(str(row["nav_total_nok"])),
            nav_per_share_nok=Decimal(str(row["nav_per_share_nok"])),
            otec_price_nok=(
                Decimal(str(row["otec_price_nok"])) if row["otec_price_nok"] is not None else None
            ),
            cash_estimate_nok=Decimal(str(row["cash_estimate_nok"])),
            shares_outstanding=int(row["shares_outstanding"]),
            accounting_option_liability_nok=accounting_option,
            economic_option_value_nok=economic_option,
        )
