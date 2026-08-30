from __future__ import annotations

from decimal import Decimal

import pytest

from app.discount_history import _apply_other_share_change_split
from app.historical_investment_attribution import (
    apply_historical_life360_change_split,
)


def test_alliance_venture_is_split_from_other_ona_without_changing_total() -> None:
    change = {
        "drivers": [
            {
                "key": "other_ona",
                "label": "Øvrige nettoeiendeler",
                "amount_mnok": 10.0,
                "per_share_nok": 0.10,
                "impact_kind": "TOTAL_AND_PER_SHARE",
                "details": {
                    "start_amount_mnok": 100.0,
                    "current_amount_mnok": 110.0,
                },
            }
        ],
        "share_count_change": {
            "start_shares": 100_000_000,
            "current_shares": 100_000_000,
        },
    }
    start_report = {
        "ready": True,
        "alliance_report_nok": 40_000_000,
        "resolved_report_anchor_date": "2025-12-31",
    }
    current_report = {
        "ready": True,
        "alliance_report_nok": 45_000_000,
        "resolved_report_anchor_date": "2026-06-30",
    }

    assert _apply_other_share_change_split(change, start_report, current_report)

    drivers = change["drivers"]
    alliance = next(
        item for item in drivers if item["key"] == "alliance_venture_spring"
    )
    residual = next(item for item in drivers if item["key"] == "other_ona")

    assert alliance["label"] == "Alliance Venture Spring AS"
    assert alliance["amount_mnok"] == pytest.approx(5.0)
    assert alliance["per_share_nok"] == pytest.approx(0.05)
    assert alliance["details"]["start_amount_mnok"] == pytest.approx(40.0)
    assert alliance["details"]["current_amount_mnok"] == pytest.approx(45.0)

    assert residual["label"] == "Andre rapporterte eiendeler og forpliktelser"
    assert residual["amount_mnok"] == pytest.approx(5.0)
    assert residual["per_share_nok"] == pytest.approx(0.05)
    assert sum(item["amount_mnok"] for item in drivers) == pytest.approx(10.0)
    assert sum(item["per_share_nok"] for item in drivers) == pytest.approx(0.10)


def test_alliance_history_fails_closed_before_fair_value_reporting() -> None:
    change = {
        "drivers": [
            {
                "key": "other_ona",
                "amount_mnok": 10.0,
                "per_share_nok": 0.10,
                "details": {},
            }
        ],
        "share_count_change": {
            "start_shares": 100_000_000,
            "current_shares": 100_000_000,
        },
    }
    start_report = {
        "ready": True,
        "alliance_report_nok": 5_000_000,
        "resolved_report_anchor_date": "2024-12-31",
    }
    current_report = {
        "ready": True,
        "alliance_report_nok": 45_000_000,
        "resolved_report_anchor_date": "2026-06-30",
    }

    assert not _apply_other_share_change_split(change, start_report, current_report)
    assert all(
        item.get("key") != "alliance_venture_spring" for item in change["drivers"]
    )
    assert change["drivers"][0]["amount_mnok"] == pytest.approx(10.0)
    assert change["other_share_split_status"] == {
        "ready": False,
        "reason": "historical_alliance_fair_value_not_separately_reported",
        "policy": "FAIL_CLOSED_PRE_FAIR_VALUE",
        "start_report_date": "2024-12-31",
        "current_report_date": "2026-06-30",
    }


def test_historical_life360_driver_is_reallocated_without_changing_total() -> None:
    change = {
        "drivers": [
            {
                "key": "life360",
                "label": "Life 360",
                "amount_mnok": 2.0,
                "per_share_nok": 0.02,
                "details": {},
            },
            {
                "key": "other_ona",
                "label": "Øvrige nettoeiendeler",
                "amount_mnok": 50.0,
                "per_share_nok": 0.50,
                "details": {},
            },
        ],
        "share_count_change": {
            "start_shares": 100_000_000,
            "current_shares": 100_000_000,
        },
    }
    start_state = {
        "ready": True,
        "as_of_date": "2023-08-30",
        "market_value_nok": Decimal("10000000"),
        "market_symbol": "360.AX",
        "currency": "AUD",
        "price": Decimal("20"),
        "fx_rate": Decimal("6.5"),
        "holding_quality": "DERIVED_MEDIUM_CONFIDENCE",
        "method": "ASX_CDI_3_TO_1_TIMES_AUD_NOK",
    }
    current_state = {
        "ready": True,
        "as_of_date": "2026-08-30",
        "market_value_nok": Decimal("30000000"),
        "market_symbol": "LIF",
        "currency": "USD",
        "price": Decimal("50"),
        "fx_rate": Decimal("10"),
        "holding_quality": "DERIVED_HIGH_CONFIDENCE",
        "method": "NASDAQ_COMMON_TIMES_USD_NOK",
    }

    assert apply_historical_life360_change_split(
        change, start_state, current_state
    )

    life360 = next(item for item in change["drivers"] if item["key"] == "life360")
    residual = next(item for item in change["drivers"] if item["key"] == "other_ona")
    assert life360["amount_mnok"] == pytest.approx(20.0)
    assert life360["per_share_nok"] == pytest.approx(0.20)
    assert residual["amount_mnok"] == pytest.approx(32.0)
    assert residual["per_share_nok"] == pytest.approx(0.32)
    assert sum(item["amount_mnok"] for item in change["drivers"]) == pytest.approx(52.0)
    assert sum(item["per_share_nok"] for item in change["drivers"]) == pytest.approx(0.52)
    assert life360["details"]["attribution_only"] is True
    assert life360["details"]["accounting_nav_restatement"] is False
    assert life360["details"]["start_market_symbol"] == "360.AX"
    assert life360["details"]["current_market_symbol"] == "LIF"
    assert change["life360_history_split_status"]["ready"] is True
