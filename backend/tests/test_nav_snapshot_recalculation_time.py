from __future__ import annotations

from datetime import datetime

from app.db.connection import get_connection
from app.db.migration_runner import init_database


def test_nav_snapshot_update_preserves_created_at_and_touches_updated_at(tmp_path) -> None:
    database = str(tmp_path / "nav-freshness.db")
    init_database(database)
    original = "2026-01-01T09:31:00.000Z"

    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                discount_pct, bemobi_value_nok, cash_estimate_nok,
                other_net_assets_nok, shares_outstanding, calculation_version,
                inputs_hash, status, nav_scope, components_json, quality_notes,
                created_at
            ) VALUES (
                '2026-01-01T23:59:59Z', '100', '10', '8', '20', '70', '20',
                '10', 10, 'freshness-test-v1', 'hash-1', 'ESTIMATED', 'FULL',
                '{}', 'test', ?
            )
            """,
            (original,),
        )
        connection.commit()

        inserted = connection.execute(
            """
            SELECT created_at, updated_at
            FROM nav_snapshots
            WHERE calculation_version='freshness-test-v1'
            """
        ).fetchone()
        assert inserted is not None
        assert inserted["created_at"] == original
        assert inserted["updated_at"] == original

        connection.execute(
            """
            UPDATE nav_snapshots
            SET nav_total_nok='101', inputs_hash='hash-2'
            WHERE calculation_version='freshness-test-v1'
            """
        )
        connection.commit()

        updated = connection.execute(
            """
            SELECT created_at, updated_at
            FROM nav_snapshots
            WHERE calculation_version='freshness-test-v1'
            """
        ).fetchone()

    assert updated is not None
    assert updated["created_at"] == original
    assert updated["updated_at"] != original
    assert datetime.fromisoformat(updated["updated_at"].replace("Z", "+00:00")) > datetime.fromisoformat(
        original.replace("Z", "+00:00")
    )
