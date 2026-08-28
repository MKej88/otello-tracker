from __future__ import annotations

import copy
import sys
from decimal import Decimal
from pathlib import Path

from app.nav_waterfall_settlement import apply_nav_settlement_waterfall as reference_waterfall
from app.option_settlement import nav_cash_settlement as reference_settlement
from app.option_settlement import (
    settlement_inputs_from_components as reference_component_inputs,
)
from app.option_settlement import settlement_inputs_from_daily_row as reference_daily_inputs

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from nav_waterfall_settlement import apply_nav_settlement_waterfall as worker_waterfall  # noqa: E402
from option_settlement import nav_cash_settlement as worker_settlement  # noqa: E402
from option_settlement import (  # noqa: E402
    settlement_inputs_from_components as worker_component_inputs,
)
from option_settlement import (  # noqa: E402
    settlement_inputs_from_daily_row as worker_daily_inputs,
)


def test_option_inputs_reject_non_finite_numbers_and_fractional_counts() -> None:
    fractional_count = {
        "other_net_assets": {
            "option_liability": {
                "inputs": {"option_count": 4.5, "strike_nok": "12.56"}
            }
        }
    }
    non_finite_strike = {
        "other_net_assets": {
            "option_liability": {
                "inputs": {"option_count": 4_100_000, "strike_nok": "NaN"}
            }
        }
    }
    non_finite_liability = {
        "option_inputs_json": '{"option_count": 4100000}',
        "option_strike_nok": "12.56",
        "option_liability_nok": "Infinity",
    }

    assert reference_component_inputs(fractional_count) is None
    assert worker_component_inputs(fractional_count) is None
    assert reference_component_inputs(non_finite_strike) is None
    assert worker_component_inputs(non_finite_strike) is None
    assert reference_daily_inputs(non_finite_liability) is None
    assert worker_daily_inputs(non_finite_liability) is None


def test_nav_cash_settlement_is_self_consistent_and_matches_worker() -> None:
    inputs = {
        "pre_option_total_nok": Decimal("250000000"),
        "shares_outstanding": 10_000_000,
        "option_count": 4_100_000,
        "strike_nok": Decimal("12.56"),
    }
    reference = reference_settlement(**inputs)
    worker = worker_settlement(**inputs)
    assert worker == reference

    expected_nav_after = (
        inputs["pre_option_total_nok"]
        + Decimal(inputs["option_count"]) * inputs["strike_nok"]
    ) / Decimal(inputs["shares_outstanding"] + inputs["option_count"])
    expected_settlement = Decimal(inputs["option_count"]) * (
        expected_nav_after - inputs["strike_nok"]
    )
    assert reference["nav_after_option_per_share_nok"] == expected_nav_after
    assert reference["settlement_nok"] == expected_settlement
    assert (
        reference["economic_total_after_settlement_nok"]
        / Decimal(inputs["shares_outstanding"])
        == expected_nav_after
    )
    assert reference["method"] == "self-consistent-nav-cash-settlement-v1"


def test_nav_cash_settlement_is_zero_below_strike() -> None:
    result = reference_settlement(
        pre_option_total_nok=Decimal("100000000"),
        shares_outstanding=10_000_000,
        option_count=4_100_000,
        strike_nok=Decimal("12.56"),
    )
    assert result["settlement_nok"] == 0
    assert result["settlement_per_option_nok"] == 0
    assert result["nav_after_option_per_share_nok"] == Decimal("10")


def _base_waterfall() -> dict:
    return {
        "ready": True,
        "quality": "RECONCILED",
        "anchor_date": "2025-12-31",
        "as_of_date": "2026-08-19",
        "anchor": {
            "full_nav_total_mnok": 200.0,
            "full_nav_per_share_nok": 20.0,
            "economic_nav_total_mnok": 194.0,
            "economic_nav_per_share_nok": 19.4,
            "shares_outstanding": 10_000_000,
        },
        "current": {
            "full_nav_total_mnok": 220.0,
            "full_nav_per_share_nok": 24.4444444444,
            "economic_nav_total_mnok": 207.0,
            "economic_nav_per_share_nok": 23.0,
            "shares_outstanding": 9_000_000,
        },
        "change": {},
        "components": [
            {"key": "bemobi", "label": "Bemobi-verdi", "amount_mnok": 30.0, "per_share_nok": 3.0, "impact_kind": "TOTAL_AND_PER_SHARE"},
            {"key": "buyback_cash", "label": "Tilbakekjøp", "amount_mnok": -10.0, "per_share_nok": -1.0, "impact_kind": "TOTAL_AND_PER_SHARE"},
            {"key": "other_cash", "label": "Øvrig cash", "amount_mnok": 0.0, "per_share_nok": 0.0, "impact_kind": "TOTAL_AND_PER_SHARE"},
            {"key": "ona_ex_option", "label": "ONA", "amount_mnok": 2.0, "per_share_nok": 0.2, "impact_kind": "TOTAL_AND_PER_SHARE"},
            {"key": "accounting_option", "label": "Regnskapsført opsjon", "amount_mnok": -2.0, "per_share_nok": -0.2, "impact_kind": "TOTAL_AND_PER_SHARE"},
            {"key": "cash_fx", "label": "Valuta", "amount_mnok": 1.0, "per_share_nok": 0.1, "impact_kind": "TOTAL_AND_PER_SHARE"},
            {"key": "option_overhang", "label": "Overheng", "amount_mnok": -4.0, "per_share_nok": -0.4, "impact_kind": "TOTAL_AND_PER_SHARE"},
            {"key": "operating_costs", "label": "Drift", "amount_mnok": -3.0, "per_share_nok": -0.3, "impact_kind": "TOTAL_AND_PER_SHARE"},
            {"key": "share_count", "label": "Færre aksjer", "amount_mnok": None, "per_share_nok": 1.0, "impact_kind": "PER_SHARE_ONLY"},
        ],
        "reconciliation": {},
    }


def test_waterfall_replaces_accounting_and_black_scholes_with_one_settlement_driver() -> None:
    inputs = {
        "anchor_option_inputs": (Decimal("2000000"), 4_100_000, Decimal("12.56")),
        "current_option_inputs": (Decimal("4000000"), 4_100_000, Decimal("12.56")),
    }
    reference = reference_waterfall(copy.deepcopy(_base_waterfall()), **inputs)
    worker = worker_waterfall(copy.deepcopy(_base_waterfall()), **inputs)
    assert worker == reference

    keys = [item["key"] for item in reference["components"]]
    assert "option_settlement" in keys
    assert "accounting_option" not in keys
    assert "option_overhang" not in keys
    assert reference["quality"] == "RECONCILED"
    assert abs(reference["reconciliation"]["residual_mnok"]) < 1e-9
    assert abs(reference["reconciliation"]["per_share_residual_nok"]) < 1e-9
    assert reference["option_settlement"]["option_count"] == 4_100_000
    assert reference["option_settlement"]["method"] == "self-consistent-nav-cash-settlement-v1"


def test_routes_and_frontend_use_investor_settlement_model() -> None:
    backend = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare" / "src" / "app.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "src" / "EconomicNavPanel.tsx").read_text(encoding="utf-8")

    assert "from app.economic_nav_investor import economic_nav_summary" in backend
    assert "from economic_nav_investor import economic_nav_summary" in worker
    assert "from app.nav_waterfall_settlement import nav_waterfall_summary" in backend
    assert "from nav_waterfall_settlement import nav_waterfall_summary" in worker
    assert "Opsjoner – kontantoppgjør ved NAV" in frontend
    assert "Opsjonsforpliktelse – regnskapsført" not in frontend
    assert "Ekstra opsjonsoverheng" not in frontend
