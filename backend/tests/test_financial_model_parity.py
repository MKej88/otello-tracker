"""Compare independent Python implementations on deterministic model inputs."""
from __future__ import annotations

import copy
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.economic_nav import build_cash_bridge as reference_bridge
from app.estimated_nav_history import _build_change_attribution as reference_attribution
from app.option_settlement import nav_cash_settlement as reference_settlement

WORKER = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

from economic_nav import build_cash_bridge as worker_bridge  # noqa: E402
from estimated_nav_history import _build_change_attribution as worker_attribution  # noqa: E402
from option_settlement import nav_cash_settlement as worker_settlement  # noqa: E402

D = Decimal


@pytest.mark.parametrize("before", ["-2", "0", "12.5599", "12.56", "12.5601", "25", "100"])
@pytest.mark.parametrize("shares", [10_000_000, 70_000_000])
@pytest.mark.parametrize("options", [0, 4_100_000])
def test_option_settlement_parity_and_independent_cash_identity(before, shares, options):
    strike = D("12.56")
    pre_total = D(before) * shares
    inputs = dict(pre_option_total_nok=pre_total, shares_outstanding=shares,
                  option_count=options, strike_nok=strike)
    result = reference_settlement(**inputs)
    assert worker_settlement(**inputs) == result
    cash = result["settlement_nok"]
    after = result["nav_after_option_per_share_nok"]
    assert cash >= 0
    assert abs(after * shares + cash - pre_total) < D("0.000001")
    assert abs(cash - options * max(D(0), after - strike)) < D("0.000001")
    if options == 0 or D(before) <= strike:
        assert cash == 0
        assert after == D(before)
    else:
        assert strike < after < D(before)


@pytest.mark.parametrize("shares,options,strike", [(0, 1, "12.56"), (-1, 1, "12.56"),
                                                    (100, -1, "12.56"), (100, 1, "-1")])
def test_both_settlement_models_reject_invalid_inputs(shares, options, strike):
    for calculate in (reference_settlement, worker_settlement):
        with pytest.raises(ValueError):
            calculate(pre_option_total_nok=D("1000"), shares_outstanding=shares,
                      option_count=options, strike_nok=D(strike))


@pytest.mark.parametrize("buyback,distribution,patent,cost,fx,other", [
    ("0", "0", "0", "0", "0", "0"),
    ("-4000000", "8000000", "1000000", "250000", "-500000", "100000"),
    ("-4000000", "0", "0", "500000", "750000", "-100000"),
    ("0", "600", "600", "0", "0", "0"),
    ("0", "1000", "0", "0", "0", "0"),
    ("0", "1001", "0", "0", "0", "0"),
    ("-600", "600", "0", "0", "0", "0"),
])
@pytest.mark.parametrize("shares", [0, 70_000_000])
def test_cash_bridge_parity_and_reconciliation(buyback, distribution, patent, cost, fx, other, shares):
    buyback, distribution, patent, cost, fx, other = map(D, (buyback, distribution, patent, cost, fx, other))
    reported = D("100000000")
    modeled = reported + buyback + distribution + patent + other
    expected = modeled + fx - cost
    inputs = dict(anchor_date="2026-09-30", reported_cash_nok=reported,
                  modeled_cash_nok=modeled, shares_outstanding=shares, buyback_cash_nok=buyback,
                  bemobi_cash_nok=distribution, patent_proceeds_nok=patent,
                  operating_cost_nok=cost, cash_fx_nok=fx)
    result = reference_bridge(**inputs)
    assert worker_bridge(**inputs) == result
    assert result["estimated_cash_mnok"] == pytest.approx(float(expected / D(1000000)), abs=1e-10)
    assert result["reconciles"] is True
    visible = sum(D(str(item["amount_mnok"])) * D(1000000) for item in result["movements"])
    assert abs(visible - (expected - reported)) <= D("1000")
    if shares:
        assert result["cash_per_share_nok"] == pytest.approx(float(expected / shares), abs=1e-10)
    else:
        assert result["cash_per_share_nok"] is None


def _point(day, shares, components):
    total = sum(components.values())
    return dict(date=day, shares_outstanding=shares, nav_total_mnok=total,
                nav_per_share=total * 1_000_000 / shares if shares else 0,
                composition=[dict(key=key, amount_mnok=value, details={})
                             for key, value in components.items()])


@pytest.mark.parametrize("shares", [0, 90_000_000, 100_000_000, 110_000_000])
@pytest.mark.parametrize("market_ready", [False, True])
def test_nav_attribution_parity_and_driver_sum(shares, market_ready):
    start = _point("2026-11-18", 100_000_000, dict(bemobi=700, cash=192, ona=108, life360=0, options=0))
    current = _point("2026-11-30", shares, dict(bemobi=710, cash=196, ona=100, life360=2, options=-1))
    kwargs = dict(
        bemobi_market=dict(ready=market_ready, price_effect_nok=6_000_000, fx_effect_nok=4_000_000),
        cash_breakdown=dict(ready=True, buyback_cash_nok=-4_000_000,
                            bemobi_gross_cash_nok=10_000_000, bemobi_withholding_nok=-2_000_000,
                            bemobi_net_cash_nok=8_000_000),
        start_receivable=dict(ready=True, amount_nok=8_000_000, quality="ESTIMATED_NET"),
        current_receivable=dict(ready=True, amount_nok=0, quality="NONE"),
    )
    def calculate(model):
        return model(copy.deepcopy(start), copy.deepcopy(current), "2026-11-18", **copy.deepcopy(kwargs))
    result = calculate(reference_attribution)
    assert calculate(worker_attribution) == result
    if shares == 0:
        assert result["ready"] is False
        assert result["reason"] == "invalid_share_count"
        return
    assert result["ready"] is True
    drivers = {item["key"]: item for item in result["drivers"]}
    assert drivers["bemobi_paid"]["amount_mnok"] == 8
    assert drivers["bemobi_receivable"]["amount_mnok"] == -8
    assert drivers["buyback_cash"]["amount_mnok"] == -4
    assert "model_residual" not in drivers
    assert ("bemobi_market" in drivers) is not market_ready
    assert abs(result["reconciliation_residual_nok"]) < 1e-9
    assert sum(item["per_share_nok"] for item in drivers.values()) == pytest.approx(
        current["nav_per_share"] - start["nav_per_share"], abs=1e-9)
