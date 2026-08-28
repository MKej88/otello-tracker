from __future__ import annotations

import pytest

from app.discount_history import _apply_other_share_change_split


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
