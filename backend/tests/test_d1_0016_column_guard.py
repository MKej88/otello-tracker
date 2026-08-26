from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "cloudflare" / "migrations"


def test_d1_0016_adds_other_shares_column_without_seeding_fresh_data() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        for filename in (
            "0001_initial_schema.sql",
            "0002_reference_data.sql",
            "0004_option_liability.sql",
            "0009_bemobi_investor_facts.sql",
            "0010_bemobi_web_provenance.sql",
            "0011_norges_bank_fx_source.sql",
            "0012_bemobi_consensus_history.sql",
            "0013_life360_market_data.sql",
            "0015_life360_ir_lseg_source.sql",
        ):
            connection.executescript((MIGRATIONS / filename).read_text(encoding="utf-8"))

        assert connection.execute("SELECT COUNT(*) FROM nav_snapshots").fetchone()[0] == 0
        connection.executescript(
            (MIGRATIONS / "0016_other_shares_and_life360_report_anchor.sql").read_text(
                encoding="utf-8"
            )
        )

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(other_net_assets_reported_anchors)")
        }
        assert "other_shares_investment_reported" in columns
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM source_documents
            WHERE external_id='life360-ir-lseg:lif:2026-06-30:curated-report-anchor'
            """
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            JOIN sources s ON s.id=mp.source_id
            WHERE i.symbol='LIF'
              AND s.code='LIFE360_IR_LSEG'
              AND mp.trading_date='2026-06-30'
              AND mp.price='55.36'
            """
        ).fetchone()[0] == 0
    finally:
        connection.close()
