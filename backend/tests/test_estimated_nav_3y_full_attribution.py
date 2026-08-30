from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.discount_history import _apply_other_share_change_split
from app.estimated_nav_history import _build_change_attribution
from app.estimated_nav_history_cash_display import (
    _apply_period_interest_income_split,
    _apply_period_operating_cost_split,
)
from app.historical_investment_attribution import (
    apply_historical_life360_change_split,
)


MILLION = Decimal("1000000")


def _point(
    *,
    day: str,
    shares: int,
    composition: dict[str, float],
) -> dict:
    total_mnok = sum(composition.values())
    return {
        "date": day,
        "nav_total_mnok": total_mnok,
        "nav_per_share": total_mnok * 1_000_000 / shares,
        "shares_outstanding": shares,
        "composition": [
            {
                "key": key,
                "amount_mnok": amount,
                "details": {"operating_cost_mnok": 0.0} if key == "cash" else {},
            }
            for key, amount in composition.items()
        ],
    }


def _per_share_total(change: dict) -> Decimal:
    return sum(
        (Decimal(str(item.get("per_share_nok") or "0")) for item in change["drivers"]),
        Decimal("0"),
    )


def _numerator_total(change: dict) -> Decimal:
    return sum(
        (
            Decimal(str(item["amount_mnok"])) * MILLION
            for item in change["drivers"]
            if item.get("amount_mnok") is not None
        ),
        Decimal("0"),
    )


def test_three_year_full_attribution_reconciles_all_known_components() -> None:
    """Lock the complete 3Y investor bridge after the historical backfills.

    This deliberately spans the pre-fair-value Life360/Alliance regime. Historical
    Life360 is reallocated as investor attribution only, while Alliance must remain
    fail-closed inside other ONA. Operating cost and reported interest are display
    splits inside the residual cash driver and must never change total NAV.
    """
    start_day = "2023-08-31"
    current_day = "2026-08-30"
    assert (date.fromisoformat(current_day) - date.fromisoformat(start_day)).days == 1095

    start = _point(
        day=start_day,
        shares=100_000_000,
        composition={
            "bemobi": 500.0,
            "cash": 200.0,
            "ona": 250.0,
            "life360": 30.0,
            "options": 20.0,
        },
    )
    current = _point(
        day=current_day,
        shares=90_000_000,
        composition={
            "bemobi": 600.0,
            "cash": 180.0,
            "ona": 280.0,
            "life360": 50.0,
            "options": 10.0,
        },
    )

    change = _build_change_attribution(
        start,
        current,
        start_day,
        bemobi_market={
            "ready": True,
            "price_effect_nok": Decimal("70000000"),
            "fx_effect_nok": Decimal("30000000"),
            "start_price_brl": Decimal("12"),
            "current_price_brl": Decimal("24"),
            "start_brl_nok": Decimal("1.55"),
            "current_brl_nok": Decimal("1.90"),
            "start_price_date": start_day,
            "current_price_date": current_day,
            "start_fx_date": start_day,
            "current_fx_date": current_day,
        },
        cash_breakdown={
            "ready": True,
            "buyback_cash_nok": Decimal("-40000000"),
            "bemobi_gross_cash_nok": Decimal("35000000"),
            "bemobi_withholding_nok": Decimal("-5000000"),
            "bemobi_net_cash_nok": Decimal("30000000"),
            "daily_buyback_rows": 20,
            "weekly_buyback_rows": 50,
            "weekly_buyback_rows_superseded": 0,
            "cross_start_weekly_excluded": 1,
            "bemobi_receipt_rows": 4,
            "withholding_rows": 2,
        },
        start_receivable={
            "ready": True,
            "amount_nok": Decimal("5000000"),
            "quality": "DIRECT",
        },
        current_receivable={
            "ready": True,
            "amount_nok": Decimal("15000000"),
            "quality": "DIRECT",
        },
    )

    assert change["ready"] is True
    assert change["resolved_start"] == start_day
    assert change["current_date"] == current_day
    assert change["attribution_method"] == "SYMMETRIC_VALUE_SHARECOUNT_SHAPLEY"
    assert "model_residual" not in {item["key"] for item in change["drivers"]}

    expected_numerator_change = Decimal("120000000")
    assert _numerator_total(change) == expected_numerator_change
    expected_per_share_change = Decimal(str(change["change_per_share_nok"]))
    assert abs(_per_share_total(change) - expected_per_share_change) < Decimal("0.000000001")
    assert abs(Decimal(str(change["reconciliation_residual_nok"]))) < Decimal("0.000000001")

    # Period cash presentation: -10m total residual = -25m operating cost
    # +12m reported interest +3m genuinely unexplained/other cash movement.
    result = {"change": change}
    _apply_period_operating_cost_split(
        result,
        Decimal("25000000"),
        segments=[{"start_date": start_day, "end_date": current_day}],
    )
    _apply_period_interest_income_split(
        result,
        Decimal("12000000"),
        segments=[{"source_period": "3Y_REGRESSION"}],
    )
    other_cash = next(item for item in change["drivers"] if item["key"] == "other_cash")
    assert other_cash["amount_mnok"] == pytest.approx(-10.0)
    assert other_cash["details"]["operating_cost_mnok"] == pytest.approx(-25.0)
    assert other_cash["details"]["interest_income_mnok"] == pytest.approx(12.0)
    assert other_cash["details"]["other_movements_mnok"] == pytest.approx(3.0)
    assert change["period_operating_cost_status"]["ready"] is True
    assert change["period_interest_income_status"]["ready"] is True

    before_life360_numerator = _numerator_total(change)
    before_life360_per_share = _per_share_total(change)
    assert apply_historical_life360_change_split(
        change,
        {
            "ready": True,
            "as_of_date": start_day,
            "market_value_nok": Decimal("10000000"),
            "market_symbol": "360.AX",
            "currency": "AUD",
            "price": Decimal("18"),
            "fx_rate": Decimal("6.5"),
            "holding_quality": "DERIVED_MEDIUM_CONFIDENCE",
            "method": "ASX_CDI_3_TO_1_TIMES_AUD_NOK",
        },
        {
            "ready": True,
            "as_of_date": current_day,
            "market_value_nok": Decimal("40000000"),
            "market_symbol": "LIF",
            "currency": "USD",
            "price": Decimal("54"),
            "fx_rate": Decimal("10.0"),
            "holding_quality": "DERIVED_HIGH_CONFIDENCE",
            "method": "NASDAQ_COMMON_TIMES_USD_NOK",
        },
    )

    by_key = {item["key"]: item for item in change["drivers"]}
    assert by_key["life360"]["amount_mnok"] == pytest.approx(30.0)
    assert by_key["life360"]["details"]["attribution_only"] is True
    assert by_key["life360"]["details"]["accounting_nav_restatement"] is False
    assert by_key["other_ona"]["amount_mnok"] == pytest.approx(10.0)
    assert _numerator_total(change) == before_life360_numerator
    assert abs(_per_share_total(change) - before_life360_per_share) < Decimal("0.000000001")

    # The 3Y window starts before Otello reported separate fair values. Alliance must
    # therefore stay inside the remaining ONA residual instead of being invented.
    before_alliance_numerator = _numerator_total(change)
    before_alliance_per_share = _per_share_total(change)
    assert not _apply_other_share_change_split(
        change,
        {
            "ready": False,
            "reason": "historical_alliance_fair_value_not_separately_reported",
            "resolved_report_anchor_date": "2024-12-31",
        },
        {
            "ready": True,
            "alliance_report_nok": Decimal("45000000"),
            "resolved_report_anchor_date": "2026-06-30",
        },
    )
    assert "alliance_venture_spring" not in {item["key"] for item in change["drivers"]}
    assert change["other_share_split_status"]["policy"] == "FAIL_CLOSED_PRE_FAIR_VALUE"
    assert by_key["other_ona"]["amount_mnok"] == pytest.approx(10.0)
    assert _numerator_total(change) == before_alliance_numerator
    assert abs(_per_share_total(change) - before_alliance_per_share) < Decimal("0.000000001")

    keys = {item["key"] for item in change["drivers"]}
    assert {
        "bemobi_price",
        "bemobi_fx",
        "bemobi_paid",
        "buyback_cash",
        "other_cash",
        "bemobi_receivable",
        "other_ona",
        "life360",
        "options",
        "buyback_shares",
    } <= keys
    assert "bemobi_market" not in keys
    assert "model_residual" not in keys

    assert _numerator_total(change) == expected_numerator_change
    assert abs(_per_share_total(change) - expected_per_share_change) < Decimal("0.000000001")
    assert abs(Decimal(str(change["reconciliation_residual_nok"]))) < Decimal("0.000000001")
