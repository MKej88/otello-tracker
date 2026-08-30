from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

import pytest

from app.estimated_nav_history_cash_display import (
    _apply_period_interest_income_split,
    _period_interest_income,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE source_documents(
            id INTEGER PRIMARY KEY,
            document_type TEXT NOT NULL,
            published_at TEXT,
            url TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        )
        """
    )
    return connection


def _insert_interest_anchor(
    connection: sqlite3.Connection,
    *,
    document_id: int,
    source_period: str,
    source_start: str,
    source_end: str,
    period_days: int,
    amount_usd: str,
    fx_segments: list[dict[str, str]],
) -> None:
    connection.execute(
        """
        INSERT INTO source_documents(
            id, document_type, published_at, url, metadata_json
        ) VALUES (?, 'ECONOMIC_NAV_INTEREST_INCOME_ANCHOR', ?, ?, ?)
        """,
        (
            document_id,
            f"{source_end}T00:00:00Z",
            f"https://example.com/{source_period}.pdf",
            json.dumps(
                {
                    "source_period": source_period,
                    "source_period_start": source_start,
                    "source_period_end": source_end,
                    "period_days": period_days,
                    "amount_usd": amount_usd,
                    "fx_segments": fx_segments,
                }
            ),
        ),
    )


def test_period_interest_income_attributes_reported_interest_to_one_year_window() -> None:
    connection = _connection()
    _insert_interest_anchor(
        connection,
        document_id=1,
        source_period="2H25",
        source_start="2025-07-01",
        source_end="2025-12-31",
        period_days=184,
        amount_usd="339000",
        fx_segments=[
            {"start_date": "2025-07-01", "end_date": "2025-09-30", "usd_nok": "9.9474"},
            {"start_date": "2025-10-01", "end_date": "2025-12-31", "usd_nok": "10.1196"},
        ],
    )
    _insert_interest_anchor(
        connection,
        document_id=2,
        source_period="1H26",
        source_start="2026-01-01",
        source_end="2026-06-30",
        period_days=181,
        amount_usd="326000",
        fx_segments=[
            {"start_date": "2026-01-01", "end_date": "2026-03-31", "usd_nok": "9.6605"},
            {"start_date": "2026-04-01", "end_date": "2026-06-30", "usd_nok": "9.5815"},
        ],
    )
    connection.commit()

    result = _period_interest_income(
        connection,
        start_date="2025-08-30",
        current_date="2026-08-30",
    )

    expected_2h25 = Decimal("339000") / Decimal(184) * (
        Decimal(31) * Decimal("9.9474") + Decimal(92) * Decimal("10.1196")
    )
    expected_1h26 = Decimal("326000") / Decimal(181) * (
        Decimal(90) * Decimal("9.6605") + Decimal(91) * Decimal("9.5815")
    )

    assert result["ready"] is True
    assert result["interest_nok"] == expected_2h25 + expected_1h26
    assert float(result["interest_nok"] / Decimal("1000000")) == pytest.approx(5.4197841574)
    assert len(result["segments"]) == 4


def test_period_interest_income_does_not_forecast_beyond_latest_report() -> None:
    connection = _connection()
    _insert_interest_anchor(
        connection,
        document_id=1,
        source_period="1H26",
        source_start="2026-01-01",
        source_end="2026-06-30",
        period_days=181,
        amount_usd="326000",
        fx_segments=[
            {"start_date": "2026-01-01", "end_date": "2026-03-31", "usd_nok": "9.6605"},
            {"start_date": "2026-04-01", "end_date": "2026-06-30", "usd_nok": "9.5815"},
        ],
    )
    connection.commit()

    result = _period_interest_income(
        connection,
        start_date="2026-06-30",
        current_date="2026-08-30",
    )

    assert result["ready"] is True
    assert result["interest_nok"] == Decimal("0")
    assert result["segments"] == []


def test_interest_split_keeps_total_nav_driver_and_reduces_true_residual() -> None:
    result = {
        "ready": True,
        "change": {
            "ready": True,
            "drivers": [
                {
                    "key": "other_cash",
                    "label": "Øvrig kontantendring",
                    "amount_mnok": -17.8,
                    "per_share_nok": -0.25,
                    "details": {
                        "operating_cost_mnok": -23.4,
                        "other_movements_mnok": 5.6,
                    },
                }
            ],
        },
    }
    interest_nok = Decimal("5419784.157440547681960124910")

    updated = _apply_period_interest_income_split(
        result,
        interest_nok,
        segments=[{"source_period": "2H25"}, {"source_period": "1H26"}],
    )
    driver = updated["change"]["drivers"][0]

    assert driver["amount_mnok"] == -17.8
    assert driver["per_share_nok"] == -0.25
    assert driver["details"]["interest_income_mnok"] == pytest.approx(5.4197841574)
    assert driver["details"]["other_movements_mnok"] == pytest.approx(0.1802158426)
    assert (
        driver["details"]["operating_cost_mnok"]
        + driver["details"]["interest_income_mnok"]
        + driver["details"]["other_movements_mnok"]
        == pytest.approx(driver["amount_mnok"])
    )
    assert updated["change"]["period_interest_income_status"]["ready"] is True
