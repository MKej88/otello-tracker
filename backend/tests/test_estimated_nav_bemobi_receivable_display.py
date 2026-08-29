from __future__ import annotations

from app.estimated_nav_history_cash_display import _apply_bemobi_receivable_split


def _total_mnok(result: dict) -> float:
    return sum(item["amount_mnok"] for item in result["current"]["composition"])


def test_bemobi_receivable_is_split_out_of_fx_without_changing_nav() -> None:
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
                    "key": "fx_since_report",
                    "label": "Valutaeffekt siden siste rapport",
                    "amount_mnok": 5.0,
                    "per_share_nok": 0.05,
                    "details": {},
                },
                {
                    "key": "other_reported_assets_liabilities",
                    "label": "Andre rapporterte eiendeler og forpliktelser",
                    "amount_mnok": -10.0,
                    "per_share_nok": -0.10,
                    "details": {},
                },
            ],
        },
    }
    receivable = {
        "ready": True,
        "amount_nok": 3_000_000,
        "quality": "DIRECT",
        "components": [
            {
                "action_type": "JCP",
                "ex_date": "2026-08-20",
                "payment_date": "2026-08-28",
            }
        ],
    }

    before = _total_mnok(result)
    updated = _apply_bemobi_receivable_split(result, receivable)
    after = _total_mnok(updated)
    components = updated["current"]["composition"]

    bemobi = next(item for item in components if item["key"] == "bemobi_receivable")
    fx = next(item for item in components if item["key"] == "fx_since_report")

    assert bemobi["label"] == "Bemobi – tilgode utbytte/renter"
    assert bemobi["amount_mnok"] == 3.0
    assert bemobi["per_share_nok"] == 0.03
    assert bemobi["details"]["ex_dates"] == ["2026-08-20"]
    assert bemobi["details"]["payment_dates"] == ["2026-08-28"]
    assert fx["amount_mnok"] == 2.0
    assert fx["per_share_nok"] == 0.02
    assert before == after


def test_receivable_split_creates_offsetting_fx_when_old_net_fx_row_was_hidden() -> None:
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
                }
            ],
        },
    }
    receivable = {
        "ready": True,
        "amount_nok": 3_000_000,
        "quality": "DIRECT",
        "components": [],
    }

    before = _total_mnok(result)
    updated = _apply_bemobi_receivable_split(result, receivable)
    after = _total_mnok(updated)
    components = updated["current"]["composition"]

    bemobi = next(item for item in components if item["key"] == "bemobi_receivable")
    fx = next(item for item in components if item["key"] == "fx_since_report")

    assert bemobi["amount_mnok"] == 3.0
    assert fx["amount_mnok"] == -3.0
    assert before == after


def test_zero_bemobi_receivable_adds_no_row() -> None:
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
                }
            ],
        },
    }

    updated = _apply_bemobi_receivable_split(
        result,
        {"ready": True, "amount_nok": 0, "quality": "NONE", "components": []},
    )

    assert all(
        item["key"] != "bemobi_receivable"
        for item in updated["current"]["composition"]
    )
