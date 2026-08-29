from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

from app.estimated_nav_history_cash_display import (
    _apply_period_operating_cost_split,
    _period_operating_cost,
)


def test_period_operating_cost_is_always_a_negative_nav_driver() -> None:
    result = {
        "ready": True,
        "change": {
            "ready": True,
            "drivers": [
                {
                    "key": "other_cash",
                    "label": "Øvrig kontantendring",
                    "amount_mnok": -9.0,
                    "per_share_nok": -0.13,
                    "details": {
                        "operating_cost_mnok": 8.5,
                        "other_movements_mnok": -17.5,
                    },
                }
            ],
        },
    }

    updated = _apply_period_operating_cost_split(
        result,
        Decimal("20000000"),
        segments=[{"start_date": "2026-01-01", "end_date": "2026-08-28"}],
    )
    driver = updated["change"]["drivers"][0]

    assert driver["amount_mnok"] == -9.0
    assert driver["details"]["legacy_operating_cost_mnok"] == 8.5
    assert driver["details"]["legacy_other_movements_mnok"] == -17.5
    assert driver["details"]["operating_cost_mnok"] == -20.0
    assert driver["details"]["other_movements_mnok"] == 11.0
    assert (
        driver["details"]["operating_cost_mnok"]
        + driver["details"]["other_movements_mnok"]
        == driver["amount_mnok"]
    )


def test_period_operating_cost_spans_report_anchor_resets() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE cash_anchors(
            id INTEGER PRIMARY KEY,
            as_of_date TEXT NOT NULL,
            anchor_type TEXT NOT NULL
        );
        CREATE TABLE source_documents(
            id INTEGER PRIMARY KEY,
            published_at TEXT NOT NULL,
            document_type TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE fx_rates(
            id INTEGER PRIMARY KEY,
            observed_at TEXT NOT NULL,
            base_currency TEXT NOT NULL,
            quote_currency TEXT NOT NULL,
            rate TEXT NOT NULL
        );
        """
    )
    connection.executemany(
        "INSERT INTO cash_anchors(as_of_date, anchor_type) VALUES (?, 'REPORTED')",
        [("2025-12-31",), ("2026-06-30",)],
    )

    anchors = [
        (1, "2025-07-01T00:00:00Z", "2025-07-01", "3650000"),
        (2, "2025-12-31T00:00:00Z", "2025-12-31", "7300000"),
        (3, "2026-06-30T00:00:00Z", "2026-06-30", "10950000"),
    ]
    for document_id, published_at, effective_from, amount_usd in anchors:
        connection.execute(
            "INSERT INTO source_documents(id, published_at, document_type, metadata_json) VALUES (?, ?, 'ECONOMIC_NAV_COST_ANCHOR', ?)",
            (
                document_id,
                published_at,
                json.dumps(
                    {
                        "scenario": "BASE",
                        "effective_from": effective_from,
                        "amount_usd": amount_usd,
                        "period_days": 365,
                    }
                ),
            ),
        )
    connection.executemany(
        "INSERT INTO fx_rates(observed_at, base_currency, quote_currency, rate) VALUES (?, 'USD', 'NOK', '10')",
        [
            ("2025-12-30T12:00:00Z",),
            ("2026-06-29T12:00:00Z",),
            ("2026-08-28T12:00:00Z",),
        ],
    )
    connection.commit()

    period = _period_operating_cost(
        connection,
        start_date="2025-12-30",
        current_date="2026-08-28",
    )

    assert period["ready"] is True
    assert len(period["segments"]) == 3
    assert period["segments"][0]["days"] == 1
    assert period["segments"][1]["days"] == 181
    assert period["segments"][2]["days"] == 59
    assert period["cost_nok"] == Decimal("54000000")
