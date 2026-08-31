from __future__ import annotations

from app.estimated_nav_history import _build_change_attribution


def _point(*, day: str, cash_mnok: float, ona_mnok: float) -> dict:
    return {
        "date": day,
        "nav_total_mnok": 1000.0,
        "nav_per_share": 10.0,
        "shares_outstanding": 100_000_000,
        "composition": [
            {"key": "bemobi", "amount_mnok": 700.0, "details": {}},
            {"key": "cash", "amount_mnok": cash_mnok, "details": {}},
            {"key": "ona", "amount_mnok": ona_mnok, "details": {}},
            {"key": "life360", "amount_mnok": 0.0, "details": {}},
            {"key": "options", "amount_mnok": 0.0, "details": {}},
        ],
    }


def test_payment_crossover_keeps_confirmed_distribution_visible_without_moving_nav() -> None:
    """A 1m window crossing payment must show receivable -> cash, not hide the event."""
    start = _point(day="2026-08-17", cash_mnok=192.0, ona_mnok=108.0)
    current = _point(day="2026-08-31", cash_mnok=200.0, ona_mnok=100.0)
    cash_breakdown = {
        "ready": True,
        "buyback_cash_nok": 0,
        "bemobi_gross_cash_nok": 10_000_000,
        "bemobi_withholding_nok": -2_000_000,
        "bemobi_net_cash_nok": 8_000_000,
        "bemobi_receipt_rows": 1,
        "withholding_rows": 1,
        "daily_buyback_rows": 0,
        "weekly_buyback_rows": 0,
        "weekly_buyback_rows_superseded": 0,
        "cross_start_weekly_excluded": 0,
    }
    start_receivable = {"ready": True, "amount_nok": 8_000_000, "quality": "CONFIRMED"}
    current_receivable = {"ready": True, "amount_nok": 0, "quality": "NONE"}

    result = _build_change_attribution(
        start,
        current,
        "2026-08-01",
        bemobi_market={"ready": False},
        cash_breakdown=cash_breakdown,
        start_receivable=start_receivable,
        current_receivable=current_receivable,
    )

    assert result["ready"] is True
    drivers = {driver["key"]: driver for driver in result["drivers"]}

    assert drivers["bemobi_paid"]["amount_mnok"] == 8.0
    assert drivers["bemobi_paid"]["details"]["gross_mnok"] == 10.0
    assert drivers["bemobi_paid"]["details"]["withholding_mnok"] == -2.0
    assert drivers["bemobi_receivable"]["amount_mnok"] == -8.0
    assert drivers["bemobi_receivable"]["details"]["start_mnok"] == 8.0
    assert drivers["bemobi_receivable"]["details"]["current_mnok"] == 0.0

    # The payment is a balance-sheet reclassification: receivable down, cash up.
    assert drivers["bemobi_paid"]["per_share_nok"] + drivers["bemobi_receivable"]["per_share_nok"] == 0.0
    assert result["change_per_share_nok"] == 0.0
    assert abs(result["reconciliation_residual_nok"] or 0.0) < 1e-12
