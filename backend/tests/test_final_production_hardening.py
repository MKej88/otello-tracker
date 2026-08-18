from __future__ import annotations

import json
from pathlib import Path

from app.buybacks import market_activity_status
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.jobs.bootstrap_production import run_bootstrap


def test_economic_nav_inputs_are_seeded_as_source_backed_documents(tmp_path: Path) -> None:
    database = tmp_path / "economic-inputs.db"
    init_database(str(database))
    result = seed_curated_history(str(database))

    assert result["economic_nav_inputs"]["operating_cost_anchors"] == 2
    assert result["economic_nav_inputs"]["cash_fx_exposure_anchors"] == 1

    with get_connection(str(database)) as connection:
        rows = connection.execute(
            """
            SELECT document_type, metadata_json
            FROM source_documents
            WHERE document_type IN (
                'ECONOMIC_NAV_COST_ANCHOR',
                'ECONOMIC_NAV_CASH_FX_ANCHOR'
            )
            ORDER BY document_type, id
            """
        ).fetchall()

    assert len(rows) == 3
    cash_row = next(row for row in rows if row["document_type"] == "ECONOMIC_NAV_CASH_FX_ANCHOR")
    metadata = json.loads(cash_row["metadata_json"])
    assert metadata["total_cash_usd"] == "15881000"
    assert sum(int(item["usd_equivalent"]) for item in metadata["exposures"]) == 15_881_000
    assert {item["currency"] for item in metadata["exposures"]} == {"USD", "BRL", "UNALLOCATED"}
    assert metadata["policy"] == "REVALUE_DOCUMENTED_USD_BRL_ONLY_KEEP_UNALLOCATED_FIXED"


def test_clean_bootstrap_seeds_buyback_volume_history_even_without_network(tmp_path: Path) -> None:
    database = tmp_path / "bootstrap.db"
    result = run_bootstrap(str(database), target_date="2026-08-18", fetch_network=False)

    activity = market_activity_status(str(database))
    assert result["steps"]["otec_activity_history"]["rows"] >= 20
    assert activity["positive_days"] >= 20
