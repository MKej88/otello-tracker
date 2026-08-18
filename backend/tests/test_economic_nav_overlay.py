from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from app.economic_nav import build_economic_nav_overlay as reference_overlay

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.economic_nav import build_economic_nav_overlay as worker_overlay  # noqa: E402


def _inputs(**overrides):
    values = {
        "as_of_date": "2026-08-14",
        "cash_anchor_date": "2025-12-31",
        "usd_nok": Decimal("10.00"),
        "usd_nok_date": "2026-08-14",
        "nav_total_nok": Decimal("1490400000"),
        "nav_per_share_nok": Decimal("21.86"),
        "otec_price_nok": Decimal("17.20"),
        "cash_estimate_nok": Decimal("111200000"),
        "shares_outstanding": 68170000,
        "accounting_option_liability_nok": Decimal("2600000"),
        "economic_option_value_nok": Decimal("24200000"),
        "base_operating_cost_usd": Decimal("1021000"),
        "base_operating_cost_period_days": 184,
        "conservative_operating_cost_usd": Decimal("2641000"),
        "conservative_operating_cost_period_days": 365,
        "base_cost_metadata": {
            "source_period": "2H25",
            "source_measure": "recurring operating expenses",
            "source_document_id": 1001,
            "effective_from": "2025-12-31",
        },
        "conservative_cost_metadata": {
            "source_period": "FY25_AUDITED",
            "source_measure": "audited operating expenses excluding stock compensation",
            "source_document_id": 1002,
            "effective_from": "2025-12-31",
        },
    }
    values.update(overrides)
    return values


def test_economic_overlay_is_identical_in_reference_and_worker() -> None:
    expected = reference_overlay(**_inputs())
    actual = worker_overlay(**_inputs())

    assert actual == expected
    assert expected["ready"] is True
    assert expected["option"]["unrecognized_overhang_mnok"] == 21.6
    assert expected["operating_costs"]["days_since_anchor"] == 226
    assert expected["operating_costs"]["base_mnok"] > 12
    assert expected["operating_costs"]["conservative_mnok"] > expected["operating_costs"]["base_mnok"]
    assert 2.02 < expected["operating_costs"]["base_annualized_usd_m"] < 2.03
    assert expected["operating_costs"]["conservative_annualized_usd_m"] == 2.641
    assert expected["operating_costs"]["method"] == "source-backed-operating-cost-anchor-v3"
    assert expected["operating_costs"]["source_document_id"] == 1001
    assert expected["nav_per_share"] < expected["accounting_nav_per_share"]
    assert expected["conservative_nav_per_share"] < expected["nav_per_share"]
    assert expected["discount_pct"] > expected["conservative_discount_pct"]
    assert expected["operating_costs"]["interest_income_included"] is False


def test_operating_cost_accrual_resets_at_new_cash_anchor() -> None:
    result = reference_overlay(
        **_inputs(
            as_of_date="2026-06-30",
            cash_anchor_date="2026-06-30",
            cash_estimate_nok=Decimal("150000000"),
        )
    )

    assert result["operating_costs"]["days_since_anchor"] == 0
    assert result["operating_costs"]["base_mnok"] == 0.0
    assert result["operating_costs"]["conservative_mnok"] == 0.0
    assert result["economic_cash_mnok"] == 150.0
    assert result["nav_per_share"] < result["accounting_nav_per_share"]


def test_option_overhang_never_becomes_negative() -> None:
    inputs = _inputs(
        as_of_date="2025-12-31",
        cash_anchor_date="2025-12-31",
        accounting_option_liability_nok=Decimal("30000000"),
        economic_option_value_nok=Decimal("24000000"),
    )
    result = reference_overlay(**inputs)

    expected_per_share = float(inputs["nav_total_nok"] / Decimal(inputs["shares_outstanding"]))
    assert result["option"]["unrecognized_overhang_mnok"] == 0.0
    assert result["nav_per_share"] == expected_per_share


def test_positive_documented_cash_fx_can_raise_economic_nav_without_touching_accounting_nav() -> None:
    base = reference_overlay(**_inputs(as_of_date="2025-12-31", cash_anchor_date="2025-12-31"))
    adjusted = reference_overlay(
        **_inputs(
            as_of_date="2025-12-31",
            cash_anchor_date="2025-12-31",
            cash_fx_adjustment_nok=Decimal("10000000"),
            cash_fx_details={
                "quality": "PARTIAL_EXPOSURE_REVALUATION",
                "coverage_pct": 84.29,
                "adjustment_mnok": 10.0,
            },
        )
    )

    expected_delta = 10_000_000 / 68_170_000
    assert adjusted["accounting_nav_per_share"] == base["accounting_nav_per_share"]
    assert abs((adjusted["nav_per_share"] - base["nav_per_share"]) - expected_delta) < 1e-12
    assert adjusted["economic_cash_mnok"] - base["economic_cash_mnok"] == 10.0
    assert adjusted["cash_fx"]["coverage_pct"] == 84.29
