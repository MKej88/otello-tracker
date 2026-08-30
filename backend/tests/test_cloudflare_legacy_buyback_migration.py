from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.estimated_nav_history import _cash_breakdown
from app.history import seed_curated_history


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "cloudflare"
    / "migrations"
    / "0026_legacy_2023_h1_2024_buybacks.sql"
)


def _apply_production_backfill(database: str) -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    with get_connection(database) as connection:
        connection.executescript(sql)


def test_production_d1_backfill_reconstructs_2023_program_and_is_idempotent(tmp_path) -> None:
    database = str(tmp_path / "legacy-buybacks.db")
    init_database(database)
    seed_curated_history(database)

    _apply_production_backfill(database)

    with get_connection(database) as connection:
        program = connection.execute(
            """
            SELECT COUNT(*) AS n,
                   SUM(b.shares) AS shares,
                   SUM(CAST(b.amount_nok AS INTEGER)) AS amount,
                   MAX(b.trade_date) AS last_date
            FROM buybacks b
            JOIN buyback_programs p ON p.id=b.program_id
            WHERE p.external_program_id='otec-buyback-2023-06-20'
            """
        ).fetchone()
        cash = connection.execute(
            """
            SELECT COUNT(*) AS n, SUM(CAST(c.amount_nok AS INTEGER)) AS amount
            FROM cash_movements c
            JOIN buybacks b ON b.id=c.buyback_id
            JOIN buyback_programs p ON p.id=b.program_id
            WHERE p.external_program_id='otec-buyback-2023-06-20'
              AND c.movement_type='OTELLO_BUYBACK'
            """
        ).fetchone()
        may31 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from='2024-05-31'
              AND notes LIKE 'Treasury shares from weekly %'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        feb9_source = connection.execute(
            """
            SELECT sd.metadata_json
            FROM source_documents sd
            JOIN sources s ON s.id=sd.source_id
            WHERE s.code='MANUAL'
              AND sd.external_id LIKE '%2024-02-11-otello-corporation-share-buyback-program-status'
            LIMIT 1
            """
        ).fetchone()
        attribution = _cash_breakdown(
            connection,
            start_date="2023-08-30",
            current_date="2024-06-30",
        )

    assert dict(program) == {
        "n": 50,
        "shares": 3_688_364,
        "amount": 31_307_006,
        "last_date": "2024-05-31",
    }
    assert dict(cash) == {"n": 50, "amount": -31_307_006}
    assert dict(may31) == {
        "total_shares": 91_099_729,
        "treasury_shares": 3_688_364,
        "outstanding_shares": 87_411_365,
    }

    metadata = json.loads(feb9_source["metadata_json"])
    assert metadata["source_quality"] == "CURATED_OFFICIAL_TRANSCRIPTION"
    assert metadata["reconciliation"] == "CUMULATIVE_PROGRAM_CONTROL"
    assert metadata["raw_weekly_amount_nok"] == "36322"
    assert metadata["raw_treasury_shares"] == 3_273_827

    assert attribution["buyback_cash_nok"] == Decimal("-9696236")
    assert attribution["weekly_buyback_rows"] == 39
    assert attribution["cross_start_weekly_excluded"] == 1

    # Wrangler only applies each migration once, but the SQL itself is intentionally
    # repeat-safe so a manual/recovery execution cannot duplicate financial rows.
    _apply_production_backfill(database)
    with get_connection(database) as connection:
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM buybacks b JOIN buyback_programs p ON p.id=b.program_id
               WHERE p.external_program_id='otec-buyback-2023-06-20') AS buybacks,
              (SELECT COUNT(*) FROM cash_movements c JOIN buybacks b ON b.id=c.buyback_id
               JOIN buyback_programs p ON p.id=b.program_id
               WHERE p.external_program_id='otec-buyback-2023-06-20'
                 AND c.movement_type='OTELLO_BUYBACK') AS cash_rows,
              (SELECT COUNT(*) FROM otello_share_counts
               WHERE notes LIKE 'Treasury shares from weekly curated official backfill%') AS share_rows
            """
        ).fetchone()

    assert dict(counts) == {"buybacks": 50, "cash_rows": 50, "share_rows": 50}
