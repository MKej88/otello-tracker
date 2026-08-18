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
