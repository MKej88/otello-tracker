from __future__ import annotations

import sqlite3
from decimal import Decimal

from app.estimated_nav_history_cash_display import (
    _apply_period_patent_split,
    _period_patent_proceeds,
)


def _change_result() -> dict:
    shares = 70_000_000
    return {
        "ready": True,
        "change": {
            "ready": True,
            "share_count_change": {
                "start_shares": shares,
                "current_shares": shares,
            },
            "drivers": [
                {
                    "key": "other_cash",
                    "label": "Øvrig kontantendring",
                    "amount_mnok": 10.0,
                    "per_share_nok": 10_000_000 / shares,
                    "details": {
                        "operating_cost_mnok": -1.0,
                        "interest_income_mnok": 0.5,
                        "other_movements_mnok": 10.5,
                    },
                }
            ],
        },
    }


def test_patent_split_is_explicit_and_preserves_total_attribution() -> None:
    result = _change_result()
    drivers = result["change"]["drivers"]
    old_amount = sum(Decimal(str(item.get("amount_mnok") or 0)) for item in drivers)
    old_per_share = sum(Decimal(str(item.get("per_share_nok") or 0)) for item in drivers)

    _apply_period_patent_split(
        result,
        Decimal("6200000"),
        events=[{"movement_date": "2026-07-22", "currency": "USD", "amount_original": 650000}],
    )

    drivers = result["change"]["drivers"]
    patent = next(item for item in drivers if item["key"] == "patent_proceeds")
    other_cash = next(item for item in drivers if item["key"] == "other_cash")
    assert patent["label"] == "Patentoppgjør"
    assert patent["amount_mnok"] == 6.2
    assert round(patent["per_share_nok"], 4) == 0.0886
    assert other_cash["amount_mnok"] == 3.8
    assert other_cash["details"]["other_movements_mnok"] == 4.3

    new_amount = sum(Decimal(str(item.get("amount_mnok") or 0)) for item in drivers)
    new_per_share = sum(Decimal(str(item.get("per_share_nok") or 0)) for item in drivers)
    assert new_amount == old_amount
    assert abs(new_per_share - old_per_share) < Decimal("0.000000001")


def test_period_query_only_includes_confirmed_patent_inside_window() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE cash_movements (
            id INTEGER PRIMARY KEY,
            movement_date TEXT,
            amount_nok REAL,
            amount_original REAL,
            currency TEXT,
            description TEXT,
            external_movement_id TEXT,
            source_document_id INTEGER,
            identified_type TEXT,
            confidence TEXT
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO cash_movements (
            movement_date, amount_nok, amount_original, currency, description,
            external_movement_id, source_document_id, identified_type, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("2026-07-22", 6_200_000, 650_000, "USD", "Final patent instalment", "patent:1", 1, "PATENT_PROCEEDS", "CONFIRMED"),
            ("2026-07-01", 9_000_000, 900_000, "USD", "Old patent payment", "patent:0", 1, "PATENT_PROCEEDS", "CONFIRMED"),
            ("2026-08-01", 1_000_000, 100_000, "USD", "Unconfirmed", "patent:2", 1, "PATENT_PROCEEDS", "ESTIMATED"),
            ("2026-08-02", 2_000_000, 200_000, "USD", "Other cash", "other:1", 1, "OTHER", "CONFIRMED"),
        ],
    )

    patent = _period_patent_proceeds(
        connection,
        start_date="2026-07-10",
        current_date="2026-09-05",
    )
    assert patent["amount_nok"] == Decimal("6200000.0")
    assert len(patent["events"]) == 1
    assert patent["events"][0]["movement_date"] == "2026-07-22"
