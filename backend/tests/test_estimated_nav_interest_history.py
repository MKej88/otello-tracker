from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from app.estimated_nav_history_cash_display import _period_interest_income
from app.history.economic_nav_inputs import load_economic_nav_inputs_manifest


def _connection_from_manifest() -> sqlite3.Connection:
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
    manifest = load_economic_nav_inputs_manifest()
    documents = manifest["documents"]
    for document_id, item in enumerate(manifest["interest_income_anchors"], start=1):
        metadata = {
            "source_period": item["source_period"],
            "source_period_start": item["source_period_start"],
            "source_period_end": item["source_period_end"],
            "period_days": item["period_days"],
            "amount_usd": item["amount_usd"],
            "fx_segments": item["fx_segments"],
        }
        connection.execute(
            """
            INSERT INTO source_documents(id, document_type, published_at, url, metadata_json)
            VALUES (?, 'ECONOMIC_NAV_INTEREST_INCOME_ANCHOR', ?, ?, ?)
            """,
            (
                document_id,
                f"{item['source_period_end']}T00:00:00Z",
                documents[item["source_key"]]["url"],
                json.dumps(metadata),
            ),
        )
    connection.commit()
    return connection


def test_manifest_interest_history_is_contiguous_from_2h23_through_1h26() -> None:
    manifest = load_economic_nav_inputs_manifest()
    anchors = manifest["interest_income_anchors"]

    assert manifest["version"] == "economic-nav-inputs-2026-08-30.2"
    assert [item["source_period"] for item in anchors] == [
        "2H23",
        "1H24",
        "2H24",
        "1H25",
        "2H25",
        "1H26",
    ]
    for previous, current in zip(anchors, anchors[1:], strict=False):
        previous_end = date.fromisoformat(previous["source_period_end"])
        current_start = date.fromisoformat(current["source_period_start"])
        assert (current_start - previous_end).days == 1


def test_three_year_view_attributes_all_source_backed_interest_history() -> None:
    connection = _connection_from_manifest()

    result = _period_interest_income(
        connection,
        start_date="2023-08-30",
        current_date="2026-08-30",
    )

    assert result["ready"] is True
    assert len(result["segments"]) == 12
    assert float(result["interest_nok"] / Decimal("1000000")) == pytest.approx(23.9534344274)


def test_2h23_anchor_preserves_reported_rounding_precision() -> None:
    manifest = load_economic_nav_inputs_manifest()
    anchor = manifest["interest_income_anchors"][0]

    assert anchor["source_period"] == "2H23"
    assert anchor["amount_usd"] == "400000"
    assert anchor["source_precision"] == "ROUNDED_TO_USD_0_1M"
