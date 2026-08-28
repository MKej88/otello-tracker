from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.economic_nav import _option_values
from app.history.economic_nav_inputs import load_economic_nav_inputs_manifest
from app.option_settlement import settlement_inputs_from_components


EXPECTED_BASE_ANCHORS = {
    "2023-06-30": ("1673000", 181),
    "2023-12-31": ("1400000", 184),
    "2024-06-30": ("1615000", 182),
    "2024-12-31": ("958000", 184),
    "2025-06-30": ("1286000", 181),
    "2025-12-31": ("1021000", 184),
    "2026-06-30": ("1473000", 181),
}


def test_source_backed_base_cost_anchors_cover_all_investor_periods() -> None:
    manifest = load_economic_nav_inputs_manifest()
    anchors = {
        item["effective_from"]: (str(item["amount_usd"]), int(item["period_days"]))
        for item in manifest["operating_cost_anchors"]
        if item["scenario"] == "BASE"
    }

    assert anchors == EXPECTED_BASE_ANCHORS
    assert min(anchors) <= "2023-08-28"
    assert max(anchors) == "2026-06-30"


def test_d1_migration_repairs_pregrant_history_for_estimated_nav() -> None:
    migration = Path(
        "cloudflare/migrations/0021_estimated_nav_history_cost_anchors.sql"
    ).read_text(encoding="utf-8")

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY,
            code TEXT NOT NULL UNIQUE
        );
        CREATE TABLE source_documents (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            external_id TEXT,
            document_type TEXT NOT NULL,
            title TEXT NOT NULL,
            published_at TEXT,
            url TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(source_id, external_id)
        );
        CREATE TABLE nav_snapshots (
            id INTEGER PRIMARY KEY,
            as_of_at TEXT NOT NULL,
            calculation_version TEXT NOT NULL,
            nav_scope TEXT NOT NULL,
            components_json TEXT NOT NULL
        );
        CREATE TABLE other_net_assets_daily_estimates (
            estimate_date TEXT PRIMARY KEY,
            option_inputs_json TEXT
        );
        INSERT INTO sources(id, code) VALUES
            (1, 'OTELLO_IR'),
            (2, 'MANUAL');
        """
    )

    components = {
        "other_net_assets": {
            "option_liability": {
                "amount_nok": "0",
                "fair_value_per_option_nok": None,
                "strike_nok": "12.5637",
                "inputs": {"program_version": "2026-08-17.1", "before_grant": True},
            }
        }
    }
    connection.execute(
        """
        INSERT INTO nav_snapshots(
            as_of_at, calculation_version, nav_scope, components_json
        ) VALUES (?, ?, ?, ?)
        """,
        (
            "2023-08-28T23:59:59Z",
            "full-market-nav-daily-v2",
            "FULL",
            json.dumps(components),
        ),
    )
    connection.execute(
        "INSERT INTO other_net_assets_daily_estimates VALUES (?, ?)",
        ("2023-08-28", json.dumps({"before_grant": True})),
    )

    connection.executescript(migration)

    cost_rows = connection.execute(
        """
        SELECT metadata_json
        FROM source_documents
        WHERE document_type='ECONOMIC_NAV_COST_ANCHOR'
        ORDER BY published_at
        """
    ).fetchall()
    inserted = {
        json.loads(row["metadata_json"])["effective_from"]: (
            str(json.loads(row["metadata_json"])["amount_usd"]),
            int(json.loads(row["metadata_json"])["period_days"]),
        )
        for row in cost_rows
    }
    assert inserted == {
        key: value
        for key, value in EXPECTED_BASE_ANCHORS.items()
        if key != "2025-12-31"
    }

    row = connection.execute(
        "SELECT components_json FROM nav_snapshots WHERE id=1"
    ).fetchone()
    assert row is not None
    repaired = json.loads(row["components_json"])

    assert _option_values(repaired) == (0, 0)
    assert settlement_inputs_from_components(repaired) == (0, 12.5637)

    daily = connection.execute(
        "SELECT option_inputs_json FROM other_net_assets_daily_estimates"
    ).fetchone()
    assert daily is not None
    daily_inputs = json.loads(daily["option_inputs_json"])
    assert daily_inputs["option_count"] == 0
    assert daily_inputs["gross_fair_value_nok"] == "0"
