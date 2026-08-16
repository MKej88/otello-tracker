import json

from app.buybacks.official_backfill import seed_known_official_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def test_material_issuer_discrepancies_are_visible_in_source_metadata(tmp_path) -> None:
    database = str(tmp_path / "metadata.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT url, metadata_json
            FROM source_documents
            WHERE url LIKE '%2024-08-11-otello-corporation-share-buyback-program-status'
               OR url LIKE '%2025-01-03-otello-corporation-share-buyback-program-status'
            ORDER BY url
            """
        ).fetchall()

    assert len(rows) == 2
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        assert metadata["issuer_text_discrepancy"] is True
        assert metadata["source_quality"] == "CURATED_OFFICIAL"
        assert metadata["discrepancy_note"]
