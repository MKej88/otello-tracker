from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from estimated_nav_history import _build_change_attribution, _cash_breakdown  # noqa: E402


def _point(*, day: str, total_mnok: float, shares: int, composition: dict[str, float]) -> dict:
    return {
        "date": day,
        "nav_total_mnok": total_mnok,
        "nav_per_share": total_mnok * 1_000_000 / shares,
        "shares_outstanding": shares,
        "composition": [
            {"key": key, "amount_mnok": amount}
            for key, amount in composition.items()
        ],
    }


def test_change_attribution_splits_bemobi_distributions_and_buybacks() -> None:
    start = _point(
        day="2026-07-01",
        total_mnok=100.0,
        shares=100_000_000,
        composition={
            "bemobi": 50.0,
            "cash": 30.0,
            "ona": 20.0,
            "life360": 0.0,
            "options": 0.0,
        },
    )
    current = _point(
        day="2026-08-01",
        total_mnok=96.0,
        shares=90_000_000,
        composition={
            "bemobi": 55.0,
            "cash": 24.0,
            "ona": 17.0,
            "life360": 1.0,
            "options": -1.0,
        },
    )

    result = _build_change_attribution(
        start,
        current,
        "2026-07-01",
        bemobi_market={
            "ready": True,
            "price_effect_nok": Decimal("3000000"),
            "fx_effect_nok": Decimal("2000000"),
            "start_price_brl": Decimal("20"),
            "current_price_brl": Decimal("21"),
            "start_brl_nok": Decimal("1.80"),
            "current_brl_nok": Decimal("1.85"),
        },
        cash_breakdown={
            "ready": True,
            "buyback_cash_nok": Decimal("-4000000"),
            "bemobi_gross_cash_nok": Decimal("3000000"),
            "bemobi_withholding_nok": Decimal("-1000000"),
            "bemobi_net_cash_nok": Decimal("2000000"),
        },
        start_receivable={"ready": True, "amount_nok": Decimal("5000000"), "quality": "DIRECT"},
        current_receivable={"ready": True, "amount_nok": Decimal("6000000"), "quality": "DIRECT"},
    )

    assert result["ready"] is True
    assert result["attribution_method"] == "SYMMETRIC_VALUE_SHARECOUNT_SHAPLEY"
    by_key = {item["key"]: item for item in result["drivers"]}
    assert "bemobi_market" not in by_key
    assert by_key["bemobi_price"]["amount_mnok"] == 3.0
    assert by_key["bemobi_fx"]["amount_mnok"] == 2.0
    assert by_key["bemobi_paid"]["amount_mnok"] == 2.0
    assert by_key["bemobi_receivable"]["amount_mnok"] == 1.0
    assert by_key["buyback_cash"]["amount_mnok"] == -4.0
    assert by_key["buyback_shares"]["amount_mnok"] is None
    assert by_key["buyback_shares"]["details"]["shares_reduced"] == 10_000_000
    assert by_key["buyback_shares"]["per_share_nok"] > 0
    assert by_key["other_cash"]["details"]["operating_cost_mnok"] == 0.0
    assert by_key["other_cash"]["details"]["other_movements_mnok"] == -4.0
    assert "model_residual" not in by_key

    driver_sum = sum(Decimal(str(item["per_share_nok"])) for item in result["drivers"])
    expected = Decimal(str(result["change_per_share_nok"]))
    assert abs(driver_sum - expected) < Decimal("0.000000001")
    assert abs(Decimal(str(result["reconciliation_residual_nok"]))) < Decimal("0.000000001")


def test_cash_breakdown_prefers_daily_buybacks_over_weekly_duplicate() -> None:
    class Repository:
        async def all(self, _query, _params):
            return [
                {
                    "movement_date": "2026-08-07",
                    "movement_type": "OTELLO_BUYBACK",
                    "amount_nok": -3_000_000,
                    "description": "during 2026-08-03–2026-08-07",
                    "external_movement_id": "weekly:1",
                    "buyback_id": 10,
                },
                {
                    "movement_date": "2026-08-04",
                    "movement_type": "OTELLO_BUYBACK_DAILY",
                    "amount_nok": -1_000_000,
                    "description": "daily",
                    "external_movement_id": "daily:1",
                    "buyback_id": 10,
                },
                {
                    "movement_date": "2026-08-05",
                    "movement_type": "OTELLO_BUYBACK_DAILY",
                    "amount_nok": -2_000_000,
                    "description": "daily",
                    "external_movement_id": "daily:2",
                    "buyback_id": 10,
                },
                {
                    "movement_date": "2026-08-06",
                    "movement_type": "BEMOBI_DIVIDEND",
                    "amount_nok": 10_000_000,
                    "description": "Bemobi dividend",
                    "external_movement_id": "bemobi-dividend:1",
                    "buyback_id": None,
                },
                {
                    "movement_date": "2026-08-06",
                    "movement_type": "TAX",
                    "amount_nok": -1_500_000,
                    "description": "Bemobi JCP withholding tax",
                    "external_movement_id": "bemobi-withholding:1",
                    "buyback_id": None,
                },
            ]

    result = asyncio.run(
        _cash_breakdown(
            Repository(),
            start_date="2026-08-01",
            current_date="2026-08-10",
        )
    )

    assert result["buyback_cash_nok"] == Decimal("-3000000")
    assert result["daily_buyback_rows"] == 2
    assert result["weekly_buyback_rows"] == 0
    assert result["weekly_buyback_rows_superseded"] == 1
    assert result["bemobi_net_cash_nok"] == Decimal("8500000")
