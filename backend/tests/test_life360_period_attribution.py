from __future__ import annotations

import pytest

from app.historical_investment_attribution import apply_historical_life360_change_split


def _change(*, life360_mnok: float = 0.0, other_ona_mnok: float = 100.0) -> dict:
    return {
        "drivers": [
            {
                "key": "life360",
                "label": "Life 360",
                "amount_mnok": life360_mnok,
                "per_share_nok": 0.0,
                "details": {},
            },
            {
                "key": "other_ona",
                "label": "Andre ONA",
                "amount_mnok": other_ona_mnok,
                "per_share_nok": other_ona_mnok / 100.0,
                "details": {},
            },
        ],
        "share_count_change": {
            "start_shares": 100_000_000,
            "current_shares": 100_000_000,
        },
    }


def _state(
    *,
    day: str,
    symbol: str,
    currency: str,
    shares: int,
    price: float,
    fx: float,
    quote_units_per_common: float = 1.0,
) -> dict:
    quote_units = shares * quote_units_per_common
    return {
        "ready": True,
        "as_of_date": day,
        "market_symbol": symbol,
        "currency": currency,
        "shares": shares,
        "quote_units_per_common": quote_units_per_common,
        "quote_units": quote_units,
        "price": price,
        "fx_rate": fx,
        "market_value_nok": quote_units * price * fx,
        "holding_quality": "TEST",
        "method": "TEST_MARK_TO_MARKET",
    }


def test_same_listing_period_exposes_exact_price_fx_and_holding_split() -> None:
    change = _change()
    start = _state(
        day="2025-09-04",
        symbol="LIF",
        currency="USD",
        shares=50_000,
        price=40.0,
        fx=10.0,
    )
    current = _state(
        day="2026-09-04",
        symbol="LIF",
        currency="USD",
        shares=40_000,
        price=50.0,
        fx=9.0,
    )

    assert apply_historical_life360_change_split(change, start, current)

    life360 = next(item for item in change["drivers"] if item["key"] == "life360")
    details = life360["details"]
    assert details["display_available"] is True
    assert details["period_breakdown_available"] is True
    assert details["attribution_currency"] == "USD"
    assert details["price_effect_mnok"] == pytest.approx(5.0)
    assert details["fx_effect_mnok"] == pytest.approx(-2.5)
    assert details["holding_effect_mnok"] == pytest.approx(-4.5)
    assert life360["amount_mnok"] == pytest.approx(-2.0)
    assert (
        details["price_effect_mnok"]
        + details["fx_effect_mnok"]
        + details["holding_effect_mnok"]
    ) == pytest.approx(life360["amount_mnok"])
    assert abs(details["period_breakdown_residual_nok"]) < 1e-9


def test_cross_listing_three_year_period_keeps_net_effect_without_fake_fx_split() -> None:
    change = _change(life360_mnok=30.0, other_ona_mnok=10.0)
    start = _state(
        day="2023-09-04",
        symbol="360.AX",
        currency="AUD",
        shares=50_000,
        price=8.0,
        fx=6.5,
        quote_units_per_common=3.0,
    )
    current = _state(
        day="2026-09-04",
        symbol="LIF",
        currency="USD",
        shares=40_000,
        price=50.0,
        fx=9.0,
    )

    assert apply_historical_life360_change_split(change, start, current)

    life360 = next(item for item in change["drivers"] if item["key"] == "life360")
    details = life360["details"]
    assert details["display_available"] is True
    assert details["period_breakdown_available"] is False
    assert details["period_breakdown_reason"] == "market_listing_or_currency_changed"
    assert "price_effect_mnok" not in details
    assert "fx_effect_mnok" not in details
    assert life360["amount_mnok"] == pytest.approx(10.2)
