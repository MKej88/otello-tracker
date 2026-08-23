from decimal import Decimal

from app.economic_nav_investor import (
    CONSERVATIVE_COST_POLICY,
    _apply_conservative_cost_floor,
)


def test_conservative_cost_floor_uses_base_when_ttm_run_rate_is_lower() -> None:
    operating = {
        "base_mnok": 3.931067529281768,
        "conservative_mnok": 3.300577365479452,
        "base_annualized_usd_m": 2.970414364640884,
        "conservative_annualized_usd_m": 2.494,
    }

    base_cost, conservative_cost, public = _apply_conservative_cost_floor(operating)

    assert conservative_cost == base_cost
    assert public["conservative_floor_applied"] is True
    assert public["conservative_policy"] == CONSERVATIVE_COST_POLICY
    assert Decimal(str(public["conservative_mnok"])) == Decimal(str(operating["base_mnok"]))
    assert Decimal(str(public["conservative_source_mnok"])) == Decimal(
        str(operating["conservative_mnok"])
    )
    assert public["conservative_annualized_usd_m"] == operating["base_annualized_usd_m"]
    assert public["conservative_source_annualized_usd_m"] == operating[
        "conservative_annualized_usd_m"
    ]


def test_conservative_cost_floor_keeps_higher_source_scenario() -> None:
    operating = {
        "base_mnok": 3.0,
        "conservative_mnok": 4.0,
        "base_annualized_usd_m": 2.5,
        "conservative_annualized_usd_m": 3.5,
    }

    base_cost, conservative_cost, public = _apply_conservative_cost_floor(operating)

    assert conservative_cost > base_cost
    assert public["conservative_floor_applied"] is False
    assert public["conservative_mnok"] == 4.0
    assert public["conservative_annualized_usd_m"] == 3.5
