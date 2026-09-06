import pytest

from app.main import _sync_economic_with_otec_quote, _sync_summary_with_otec_quote


def _quote(price: float = 17.98) -> dict:
    return {
        "ready": True,
        "last": price,
        "last_updated_at": "2026-09-04T16:20:00+02:00",
        "trading_date": "2026-09-04",
        "last_price_type": "CLOSE",
        "source": "EURONEXT",
        "changes": {"daily_pct": -0.11},
    }


def test_summary_uses_canonical_otec_quote_for_price_and_discount() -> None:
    summary = {
        "ready": True,
        "nav_per_share": 24.07,
        "otec_price": 17.84,
        "nav_discount_pct": 25.9,
        "changes": {"otec_pct": -0.5, "discount_pp": 0.4},
        "nav_discount_insights": {
            "nav_per_share": 24.07,
            "share_price": 17.84,
            "discount_pct": 25.9,
            "upside_to_nav_pct": 34.9,
            "month_change_pp": 1.2,
            "range_1y": {"low": 10.0, "high": 35.0, "position_pct": 63.6},
        },
    }

    result = _sync_summary_with_otec_quote(summary, _quote())
    expected_discount = (1 - 17.98 / 24.07) * 100

    assert result["otec_price"] == 17.98
    assert result["nav_discount_pct"] == pytest.approx(expected_discount)
    assert result["nav_discount_insights"]["share_price"] == 17.98
    assert result["nav_discount_insights"]["discount_pct"] == pytest.approx(
        expected_discount
    )
    assert result["changes"]["otec_pct"] == -0.11
    assert result["otec_price_trading_date"] == "2026-09-04"
    assert result["otec_price_source"] == "EURONEXT"


def test_economic_nav_uses_same_quote_for_all_discount_scenarios() -> None:
    payload = {
        "ready": True,
        "nav_per_share": 24.07,
        "conservative_nav_per_share": 23.50,
        "discount_pct": 25.9,
        "conservative_discount_pct": 24.1,
    }

    result = _sync_economic_with_otec_quote(payload, _quote())

    assert result["otec_price"] == 17.98
    assert result["discount_pct"] == pytest.approx((1 - 17.98 / 24.07) * 100)
    assert result["conservative_discount_pct"] == pytest.approx(
        (1 - 17.98 / 23.50) * 100
    )


def test_missing_quote_leaves_existing_payload_untouched() -> None:
    summary = {"otec_price": 17.84, "nav_per_share": 24.07}

    assert _sync_summary_with_otec_quote(summary, {}) == summary
    assert _sync_economic_with_otec_quote(summary, {}) == summary
