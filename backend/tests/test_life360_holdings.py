from __future__ import annotations

from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def test_curated_history_seeds_source_backed_life360_holdings(tmp_path: Path) -> None:
    database_path = tmp_path / "life360-holdings.db"
    init_database(str(database_path))
    result = seed_curated_history(str(database_path))

    assert result["life360_holdings"]["anchors"] == 2
    with get_connection(str(database_path)) as connection:
        historical = connection.execute(
            """
            SELECT h.id, h.effective_from, h.effective_to, h.shares, h.quality, h.basis,
                   h.source_locator, sd.external_id, s.code AS source_code
            FROM life360_holding_anchors h
            JOIN source_documents sd ON sd.id=h.source_document_id
            JOIN sources s ON s.id=sd.source_id
            WHERE h.effective_from='2022-12-31'
            """
        ).fetchone()
        assert historical is not None
        assert historical["effective_to"] == "2025-12-30"
        assert historical["shares"] == 37_028
        assert historical["quality"] == "DERIVED_MEDIUM_CONFIDENCE"
        assert (
            historical["basis"]
            == "CONTINUITY_DERIVED_FROM_REPORTED_OWNERSHIP_AND_2025_FAIR_VALUE"
        )
        assert historical["external_id"] == "otello-annual-2024"
        assert historical["source_code"] == "OTELLO_IR"
        assert "attribution" in historical["source_locator"].lower()

        historical_provenance = connection.execute(
            """
            SELECT extraction_method, confidence, extracted_value
            FROM provenance_records
            WHERE entity_table='life360_holding_anchors'
              AND entity_id=?
              AND field_name='shares'
            """,
            (historical["id"],),
        ).fetchone()
        assert historical_provenance is not None
        assert historical_provenance["extraction_method"] == "CALCULATED"
        assert historical_provenance["confidence"] == "MEDIUM"
        assert historical_provenance["extracted_value"] == "37028"

        current = connection.execute(
            """
            SELECT h.id, h.effective_from, h.effective_to, h.shares, h.quality, h.basis,
                   h.source_locator, sd.external_id, s.code AS source_code
            FROM life360_holding_anchors h
            JOIN source_documents sd ON sd.id=h.source_document_id
            JOIN sources s ON s.id=sd.source_id
            WHERE h.effective_from='2025-12-31'
            """
        ).fetchone()
        assert current is not None
        assert current["effective_to"] is None
        assert current["shares"] == 37_028
        assert current["quality"] == "DERIVED_HIGH_CONFIDENCE"
        assert current["basis"] == "DERIVED_FROM_2025_FAIR_VALUE"
        assert current["external_id"] == "otello-annual-2025"
        assert current["source_code"] == "OTELLO_IR"
        assert "derived" in current["source_locator"].lower()

        current_provenance = connection.execute(
            """
            SELECT extraction_method, confidence, extracted_value
            FROM provenance_records
            WHERE entity_table='life360_holding_anchors'
              AND entity_id=?
              AND field_name='shares'
            """,
            (current["id"],),
        ).fetchone()
        assert current_provenance is not None
        assert current_provenance["extraction_method"] == "CALCULATED"
        assert current_provenance["confidence"] == "HIGH"
        assert current_provenance["extracted_value"] == "37028"


def test_curated_life360_holding_seed_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "life360-holdings-idempotent.db"
    init_database(str(database_path))
    seed_curated_history(str(database_path))
    seed_curated_history(str(database_path))

    with get_connection(str(database_path)) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM life360_holding_anchors").fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM provenance_records WHERE entity_table='life360_holding_anchors'"
            ).fetchone()[0]
            == 2
        )
