from __future__ import annotations

from app.db.connection import get_connection
from app.db.migration_runner import init_database


def test_broker_model_migration_retires_legacy_aggregator_data(tmp_path) -> None:
    database = str(tmp_path / "bemobi-consensus-integrity.db")
    init_database(database)

    # Recreate a pre-0031 state containing a newer legacy aggregator observation.
    with get_connection(database) as connection:
        connection.execute(
            "DELETE FROM bemobi_investor_facts "
            "WHERE fact_type='FORWARD_CONSENSUS' AND source_name='BTG Pactual'"
        )
        connection.execute(
            "DELETE FROM bemobi_forward_consensus_snapshots WHERE source_name='BTG Pactual'"
        )
        connection.execute(
            """
            INSERT INTO bemobi_investor_facts(
                fact_type, fact_key, as_of_date, payload_json, source_name, quality
            ) VALUES ('FORWARD_CONSENSUS', '2028', '2026-08-30', '{}',
                      'MarketScreener', 'PUBLIC_AGGREGATE_AUTO')
            """
        )
        connection.execute(
            """
            INSERT INTO bemobi_forward_consensus_snapshots(
                source_name, observed_date, payload_json, content_hash, quality
            ) VALUES ('MarketScreener', '2026-08-30', '{}', 'legacy-hash',
                      'PUBLIC_AGGREGATE_AUTO')
            """
        )
        connection.execute("DELETE FROM schema_migrations WHERE version='0031'")
        connection.commit()

    assert init_database(database) == ["0031"]

    with get_connection(database) as connection:
        legacy_fact_count = connection.execute(
            """
            SELECT COUNT(*) FROM bemobi_investor_facts
            WHERE fact_type='FORWARD_CONSENSUS'
              AND lower(source_name)='marketscreener'
            """
        ).fetchone()[0]
        legacy_snapshot_count = connection.execute(
            """
            SELECT COUNT(*) FROM bemobi_forward_consensus_snapshots
            WHERE lower(source_name)='marketscreener'
            """
        ).fetchone()[0]
        broker_rows = connection.execute(
            """
            SELECT fact_key, source_name, quality
            FROM bemobi_investor_facts
            WHERE fact_type='FORWARD_CONSENSUS'
            ORDER BY fact_key
            """
        ).fetchall()
        source = connection.execute(
            "SELECT is_active FROM sources WHERE code='MARKETSCREENER'"
        ).fetchone()

    assert legacy_fact_count == 0
    assert legacy_snapshot_count == 0
    assert [(row["fact_key"], row["source_name"], row["quality"]) for row in broker_rows] == [
        ("2026", "BTG Pactual", "PUBLIC_BROKER_MODEL"),
        ("2027", "BTG Pactual", "PUBLIC_BROKER_MODEL"),
    ]
    assert source["is_active"] == 0
