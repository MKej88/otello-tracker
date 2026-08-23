from __future__ import annotations

from decimal import Decimal

from app.nav_waterfall_attribution import (
    apply_market_attribution,
    symmetric_two_factor_attribution,
)


def test_symmetric_price_fx_attribution_is_exact_and_order_independent() -> None:
    forward = symmetric_two_factor_attribution(
        shares=100,
        anchor_price=Decimal("20"),
        current_price=Decimal("18"),
        anchor_fx=Decimal("2"),
        current_fx=Decimal("2.2"),
    )
    reverse = symmetric_two_factor_attribution(
        shares=100,
        anchor_price=Decimal("18"),
        current_price=Decimal("20"),
        anchor_fx=Decimal("2.2"),
        current_fx=Decimal("2"),
    )

    assert forward["total_change_nok"] == Decimal("-40.0")
    assert forward["price_effect_nok"] == Decimal("-420.0")
    assert forward["fx_effect_nok"] == Decimal("380.0")
    assert forward["price_effect_nok"] + forward["fx_effect_nok"] == forward["total_change_nok"]
    assert reverse["total_change_nok"] == -forward["total_change_nok"]
    assert reverse["price_effect_nok"] == -forward["price_effect_nok"]
    assert reverse["fx_effect_nok"] == -forward["fx_effect_nok"]


def test_market_attribution_groups_net_effects_without_changing_nav() -> None:
    result = {
        "ready": True,
        "quality": "RECONCILED",
        "anchor": {
            "shares_outstanding": 10_000_000,
            "economic_nav_total_mnok": 100.0,
            "economic_nav_per_share_nok": 10.0,
        },
        "current": {
            "shares_outstanding": 10_000_000,
            "economic_nav_total_mnok": 110.0,
            "economic_nav_per_share_nok": 11.0,
        },
        "change": {
            "economic_nav_total_mnok": 10.0,
            "economic_nav_per_share_nok": 1.0,
            "shares_outstanding": 0,
        },
        "components": [
            {
                "key": "bemobi",
                "label": "Bemobi-verdi",
                "amount_mnok": 4.0,
                "per_share_nok": 0.4,
                "impact_kind": "TOTAL_AND_PER_SHARE",
            },
            {
                "key": "ona_ex_option",
                "label": "ONA ekskl. opsjon og Bemobi-fordring",
                "amount_mnok": 1.0,
                "per_share_nok": 0.1,
                "impact_kind": "TOTAL_AND_PER_SHARE",
            },
            {
                "key": "life360_mark_to_market",
                "label": "Life360 – mark-to-market",
                "amount_mnok": 2.0,
                "per_share_nok": 0.2,
                "impact_kind": "TOTAL_AND_PER_SHARE",
            },
            {
                "key": "operating_costs",
                "label": "Estimert drift",
                "amount_mnok": 3.0,
                "per_share_nok": 0.3,
                "impact_kind": "TOTAL_AND_PER_SHARE",
            },
        ],
    }

    adjusted = apply_market_attribution(
        result,
        bemobi_attribution={
            "ready": True,
            "method": "SYMMETRIC_TWO_FACTOR_SHAPLEY",
            "total_change_nok": Decimal("4000000"),
            "price_effect_nok": Decimal("3000000"),
            "fx_effect_nok": Decimal("1000000"),
        },
        life360_attribution={
            "ready": True,
            "method": "SYMMETRIC_TWO_FACTOR_SHAPLEY",
            "total_change_nok": Decimal("2500000"),
            "price_effect_nok": Decimal("1800000"),
            "fx_effect_nok": Decimal("700000"),
            "embedded_fx_nok": Decimal("500000"),
            "mark_to_market_adjustment_nok": Decimal("2000000"),
        },
    )

    components = {item["key"]: item for item in adjusted["components"]}
    bemobi = components["bemobi"]
    life360 = components["life360_net"]
    ona = components["ona_ex_option"]

    assert bemobi["label"] == "Bemobi – netto effekt"
    assert [item["label"] for item in bemobi["breakdown"]] == ["BMOB3-kurs", "BRL/NOK"]
    assert sum(Decimal(str(item["amountMnok"])) for item in bemobi["breakdown"]) == Decimal("4.0")

    assert life360["label"] == "Life360 – netto effekt"
    assert life360["amount_mnok"] == 2.5
    assert [item["label"] for item in life360["breakdown"]] == ["LIF-kurs", "USD/NOK"]
    assert sum(Decimal(str(item["amountMnok"])) for item in life360["breakdown"]) == Decimal("2.5")
    assert ona["amount_mnok"] == 0.5

    assert adjusted["anchor"]["economic_nav_total_mnok"] == 100.0
    assert adjusted["current"]["economic_nav_total_mnok"] == 110.0
    assert adjusted["change"]["economic_nav_total_mnok"] == 10.0
    assert adjusted["quality"] == "RECONCILED"
    assert abs(adjusted["reconciliation"]["residual_mnok"]) < 1e-12
    assert abs(adjusted["reconciliation"]["per_share_residual_nok"]) < 1e-12
