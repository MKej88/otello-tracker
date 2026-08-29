from __future__ import annotations

from app.estimated_nav_history_cash_display import _apply_bemobi_paid_split


def test_bemobi_paid_is_split_out_without_changing_composition_total() -> None:
    result = {
        "ready": True,
        "current": {
            "shares_outstanding": 100_000_000,
            "composition": [
                {
                    "key": "reported_cash",
                    "label": "Kontantbeholdning",
                    "amount_mnok": 100.0,
                    "per_share_nok": 1.0,
                    "details": {"report_date": "2026-06-30"},
                },
                {
                    "key": "other_cash_since_report",
                    "label": "Andre kontantbevegelser siden siste rapport",
                    "amount_mnok": 12.0,
                    "per_share_nok": 0.12,
                    "details": {},
                },
            ],
        },
    }
    breakdown = {
        "ready": True,
        "bemobi_gross_cash_nok": 10_000_000,
        "bemobi_withholding_nok": -2_000_000,
        "bemobi_net_cash_nok": 8_000_000,
        "bemobi_receipt_rows": 1,
        "withholding_rows": 1,
    }

    before = sum(item["amount_mnok"] for item in result["current"]["composition"])
    updated = _apply_bemobi_paid_split(result, breakdown)
    components = updated["current"]["composition"]
    after = sum(item["amount_mnok"] for item in components)

    bemobi = next(item for item in components if item["key"] == "bemobi_paid_since_report")
    residual = next(item for item in components if item["key"] == "other_cash_since_report")

    assert bemobi["label"] == "Bemobi – utbetalt utbytte/renter"
    assert bemobi["amount_mnok"] == 8.0
    assert bemobi["per_share_nok"] == 0.08
    assert bemobi["details"]["gross_mnok"] == 10.0
    assert bemobi["details"]["withholding_mnok"] == -2.0
    assert residual["amount_mnok"] == 4.0
    assert residual["per_share_nok"] == 0.04
    assert before == after


def test_other_cash_row_disappears_when_it_only_contains_bemobi_payment() -> None:
    result = {
        "ready": True,
        "current": {
            "shares_outstanding": 100_000_000,
            "composition": [
                {
                    "key": "other_cash_since_report",
                    "label": "Andre kontantbevegelser siden siste rapport",
                    "amount_mnok": 8.0,
                    "per_share_nok": 0.08,
                    "details": {},
                },
            ],
        },
    }
    breakdown = {
        "ready": True,
        "bemobi_gross_cash_nok": 10_000_000,
        "bemobi_withholding_nok": -2_000_000,
        "bemobi_net_cash_nok": 8_000_000,
        "bemobi_receipt_rows": 1,
        "withholding_rows": 1,
    }

    updated = _apply_bemobi_paid_split(result, breakdown)
    keys = [item["key"] for item in updated["current"]["composition"]]

    assert "bemobi_paid_since_report" in keys
    assert "other_cash_since_report" not in keys
