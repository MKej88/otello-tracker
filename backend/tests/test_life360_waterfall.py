from __future__ import annotations

from decimal import Decimal

from app.nav_waterfall_settlement import apply_nav_settlement_waterfall


def test_life360_adjustment_is_a_reconciled_waterfall_component() -> None:
    result = {
        "ready": True,
        "anchor": {
            "shares_outstanding": 10_000_000,
            "full_nav_total_mnok": 100.0,
        },
        "current": {
            "shares_outstanding": 10_000_000,
            "full_nav_total_mnok": 100.0,
        },
        "components": [
            {
                "key": "accounting_option",
                "label": "Regnskapsført opsjon",
                "amount_mnok": 0.0,
                "per_share_nok": 0.0,
            }
        ],
    }

    adjusted = apply_nav_settlement_waterfall(
        result,
        anchor_option_inputs=(Decimal("0"), 0, Decimal("0")),
        current_option_inputs=(Decimal("0"), 0, Decimal("0")),
        life360_adjustment_nok=Decimal("10000000"),
        life360_metadata={"ready": True, "shares": 37_028, "price": 44.66},
    )

    components = {item["key"]: item for item in adjusted["components"]}
    assert components["life360_mark_to_market"]["amount_mnok"] == 10.0
    assert adjusted["current"]["economic_nav_total_mnok"] == 110.0
    assert adjusted["change"]["economic_nav_total_mnok"] == 10.0
    assert abs(adjusted["reconciliation"]["residual_mnok"]) < 1e-9
    assert adjusted["quality"] == "RECONCILED"
    assert adjusted["life360"]["shares"] == 37_028
