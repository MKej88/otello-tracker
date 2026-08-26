from __future__ import annotations

from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def test_curated_history_seeds_source_backed_life360_holding(tmp_path: Path) -> None:
    database_path = tmp_path / "life360-holdings.db"
    init_database(str(database_path))
    result = seed_curated_history(str(database_path))

    assert result["life360_holdings"]["anchors"] == 1
    with get_connection(str(database_path)) as connection:
        row = connection.execute(
            """
            SELECT h.effective_from, h.effective_to, h.shares, h.quality, h.basis,
                   h.source_locator, sd.external_id, s.code AS source_code
            FROM life360_holding_anchors h
            JOIN source_documents sd ON sd.id=h.source_document_id
            JOIN sources s ON s.id=sd.source_id
            WHERE h.effective_from='2025-12-31'
            """
        ).fetchone()
        assert row is not None
        assert row["effective_to"] is None
        assert row["shares"] == 37_028
        assert row["quality"] == "DERIVED_HIGH_CONFIDENCE"
        assert row["basis"] == "DERIVED_FROM_2025_FAIR_VALUE"
        assert row["external_id"] == "otello-annual-2025"
        assert row["source_code"] == "OTELLO_IR"
        assert "derived" in row["source_locator"].lower()

        provenance = connection.execute(
            """
            SELECT extraction_method, confidence, extracted_value
            FROM provenance_records
            WHERE entity_table='life360_holding_anchors'
              AND field_name='shares'
            """
        ).fetchone()
        assert provenance is not None
        assert provenance["extraction_method"] == "CALCULATED"
        assert provenance["confidence"] == "HIGH"
        assert provenance["extracted_value"] == "37028"


def test_curated_life360_holding_seed_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "life360-holdings-idempotent.db"
    init_database(str(database_path))
    seed_curated_history(str(database_path))
    seed_curated_history(str(database_path))

    with get_connection(str(database_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM life360_holding_anchors").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM provenance_records WHERE entity_table='life360_holding_anchors'"
        ).fetchone()[0] == 1
