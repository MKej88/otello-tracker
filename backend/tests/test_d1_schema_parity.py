from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.db.migration_runner import init_database


ROOT = Path(__file__).resolve().parents[2]
D1_SCHEMA = ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"
D1_REFERENCE_DATA = ROOT / "cloudflare" / "migrations" / "0002_reference_data.sql"
D1_OPTION_LIABILITY = ROOT / "cloudflare" / "migrations" / "0004_option_liability.sql"
D1_BEMOBI_FACTS = ROOT / "cloudflare" / "migrations" / "0009_bemobi_investor_facts.sql"
D1_BEMOBI_WEB = ROOT / "cloudflare" / "migrations" / "0010_bemobi_web_provenance.sql"
D1_NORGES_BANK = ROOT / "cloudflare" / "migrations" / "0011_norges_bank_fx_source.sql"
D1_BEMOBI_CONSENSUS = ROOT / "cloudflare" / "migrations" / "0012_bemobi_consensus_history.sql"
D1_LIFE360 = ROOT / "cloudflare" / "migrations" / "0013_life360_market_data.sql"
D1_LIFE360_IR_LSEG = ROOT / "cloudflare" / "migrations" / "0015_life360_ir_lseg_source.sql"
D1_OTHER_SHARES = ROOT / "cloudflare" / "migrations" / "0016_other_shares_and_life360_report_anchor.sql"
D1_LIFE360_HOLDINGS = ROOT / "cloudflare" / "migrations" / "0017_life360_holding_anchors.sql"
D1_OTEC_ACTIVITY_SOURCE = ROOT / "cloudflare" / "migrations" / "0018_otec_market_activity_source.sql"
D1_LIFE360_PRICE_BACKFILL = ROOT / "cloudflare" / "migrations" / "0020_life360_price_backfill.sql"
D1_BROKER_MODEL = ROOT / "cloudflare" / "migrations" / "0028_replace_aggregator_with_btg_model.sql"


def _connect_reference(tmp_path: Path) -> sqlite3.Connection:
    database_path = tmp_path / "reference.db"
    init_database(str(database_path))
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _connect_d1_shape() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(D1_SCHEMA.read_text(encoding="utf-8"))
    connection.executescript(D1_OPTION_LIABILITY.read_text(encoding="utf-8"))
    connection.executescript(D1_BEMOBI_FACTS.read_text(encoding="utf-8"))
    connection.executescript(D1_BEMOBI_WEB.read_text(encoding="utf-8"))
    connection.executescript(D1_NORGES_BANK.read_text(encoding="utf-8"))
    connection.executescript(D1_BEMOBI_CONSENSUS.read_text(encoding="utf-8"))
    connection.executescript(D1_OTHER_SHARES.read_text(encoding="utf-8"))
    connection.executescript(D1_LIFE360_HOLDINGS.read_text(encoding="utf-8"))
    return connection


def _connect_d1_pre_0016() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    for migration in (
        D1_SCHEMA,
        D1_REFERENCE_DATA,
        D1_OPTION_LIABILITY,
        D1_BEMOBI_FACTS,
        D1_BEMOBI_WEB,
        D1_NORGES_BANK,
        D1_BEMOBI_CONSENSUS,
        D1_LIFE360,
        D1_LIFE360_IR_LSEG,
    ):
        connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        row["name"]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
              AND name <> 'schema_migrations'
            ORDER BY name
            """
        )
    ]


def _table_columns(connection: sqlite3.Connection, table: str) -> list[tuple]:
    return [
        (row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"])
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    ]


def _foreign_keys(connection: sqlite3.Connection, table: str) -> list[tuple]:
    return sorted(
        (
            row["id"], row["seq"], row["table"], row["from"], row["to"],
            row["on_update"], row["on_delete"], row["match"],
        )
        for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
    )


def _explicit_indexes(connection: sqlite3.Connection, table: str) -> dict[str, tuple]:
    result: dict[str, tuple] = {}
    for row in connection.execute(f'PRAGMA index_list("{table}")'):
        if row["origin"] != "c":
            continue
        columns = tuple(
            index_row["name"]
            for index_row in connection.execute(f'PRAGMA index_info("{row["name"]}")')
        )
        result[row["name"]] = (row["unique"], row["partial"], columns)
    return result


def _normalized_triggers(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
    ).fetchall()
    return {
        row["name"]: re.sub(r"\s+", " ", row["sql"].strip()).rstrip(";")
        for row in rows
    }


def test_d1_schema_has_structural_parity_with_latest_sqlite_migrations(tmp_path: Path) -> None:
    reference = _connect_reference(tmp_path)
    d1 = _connect_d1_shape()
    try:
        reference_tables = _table_names(reference)
        d1_tables = _table_names(d1)
        assert d1_tables == reference_tables

        for table in reference_tables:
            assert _table_columns(d1, table) == _table_columns(reference, table), table
            assert _foreign_keys(d1, table) == _foreign_keys(reference, table), table
            assert _explicit_indexes(d1, table) == _explicit_indexes(reference, table), table

        assert _normalized_triggers(d1) == _normalized_triggers(reference)
        assert d1.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reference.close()
        d1.close()


def test_d1_reference_data_matches_sqlite_reference_seed(tmp_path: Path) -> None:
    reference = _connect_reference(tmp_path)
    d1 = _connect_d1_shape()
    try:
        d1.executescript(D1_REFERENCE_DATA.read_text(encoding="utf-8"))
        d1.executescript(D1_LIFE360.read_text(encoding="utf-8"))
        d1.executescript(D1_OTEC_ACTIVITY_SOURCE.read_text(encoding="utf-8"))
        d1.executescript(D1_LIFE360_PRICE_BACKFILL.read_text(encoding="utf-8"))
        d1.executescript(D1_BROKER_MODEL.read_text(encoding="utf-8"))

        source_columns = "code, name, source_type, base_url, is_official, is_active, terms_notes"
        reference_sources = [
            tuple(row)
            for row in reference.execute(f"SELECT {source_columns} FROM sources ORDER BY code")
        ]
        d1_sources = [
            tuple(row)
            for row in d1.execute(f"SELECT {source_columns} FROM sources ORDER BY code")
        ]
        assert d1_sources == reference_sources

        instrument_columns = (
            "symbol, name, asset_type, exchange_mic, currency, isin, source_symbol, is_active"
        )
        reference_instruments = [
            tuple(row)
            for row in reference.execute(
                f"SELECT {instrument_columns} FROM instruments ORDER BY symbol"
            )
        ]
        d1_instruments = [
            tuple(row)
            for row in d1.execute(
                f"SELECT {instrument_columns} FROM instruments ORDER BY symbol"
            )
        ]
        assert d1_instruments == reference_instruments
    finally:
        reference.close()
        d1.close()


def test_d1_0016_does_not_seed_data_on_fresh_bootstrap_target() -> None:
    d1 = _connect_d1_pre_0016()
    try:
        assert d1.execute("SELECT COUNT(*) FROM nav_snapshots").fetchone()[0] == 0
        d1.executescript(D1_OTHER_SHARES.read_text(encoding="utf-8"))
        document_count = d1.execute(
            """
            SELECT COUNT(*)
            FROM source_documents
            WHERE external_id='life360-ir-lseg:lif:2026-06-30:curated-report-anchor'
            """
        ).fetchone()[0]
        price_count = d1.execute(
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
        ).fetchone()[0]
        assert document_count == 0
        assert price_count == 0
    finally:
        d1.close()


def test_d1_0016_backfills_existing_production_database() -> None:
    d1 = _connect_d1_pre_0016()
    try:
        d1.execute(
            """
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, bemobi_value_nok,
                cash_estimate_nok, other_net_assets_nok, shares_outstanding,
                calculation_version, inputs_hash, status, nav_scope
            ) VALUES (
                '2026-06-30T23:59:59Z', '1000000', '1.00', '800000',
                '150000', '50000', 1000000,
                'migration-0016-regression', 'migration-0016-regression', 'OK', 'FULL'
            )
            """
        )
        d1.executescript(D1_OTHER_SHARES.read_text(encoding="utf-8"))
        document_count = d1.execute(
            """
            SELECT COUNT(*)
            FROM source_documents
            WHERE external_id='life360-ir-lseg:lif:2026-06-30:curated-report-anchor'
            """
        ).fetchone()[0]
        price = d1.execute(
            """
            SELECT mp.price, mp.currency, mp.quality, s.code AS source_code
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            JOIN sources s ON s.id=mp.source_id
            WHERE i.symbol='LIF'
              AND s.code='LIFE360_IR_LSEG'
              AND mp.trading_date='2026-06-30'
            ORDER BY mp.id DESC
            LIMIT 1
            """
        ).fetchone()
        assert document_count == 1
        assert price is not None
        assert price["price"] == "55.36"
        assert price["currency"] == "USD"
        assert price["quality"] == "DIRECT"
        assert price["source_code"] == "LIFE360_IR_LSEG"
    finally:
        d1.close()


def test_d1_0017_does_not_seed_holding_on_fresh_bootstrap_target() -> None:
    d1 = _connect_d1_pre_0016()
    try:
        d1.executescript(D1_OTHER_SHARES.read_text(encoding="utf-8"))
        d1.executescript(D1_LIFE360_HOLDINGS.read_text(encoding="utf-8"))
        assert d1.execute("SELECT COUNT(*) FROM life360_holding_anchors").fetchone()[0] == 0
    finally:
        d1.close()


def test_d1_0017_backfills_existing_production_holding() -> None:
    d1 = _connect_d1_pre_0016()
    try:
        d1.executescript(D1_OTHER_SHARES.read_text(encoding="utf-8"))
        otello_ir_id = d1.execute("SELECT id FROM sources WHERE code='OTELLO_IR'").fetchone()[0]
        d1.execute(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, url
            ) VALUES (?, 'otello-annual-2025', 'ANNUAL_REPORT',
                      'Otello Corporation ASA - Annual Report 2025',
                      'https://example.test/otello-annual-2025.pdf')
            """,
            (otello_ir_id,),
        )
        d1.executescript(D1_LIFE360_HOLDINGS.read_text(encoding="utf-8"))
        row = d1.execute(
            """
            SELECT h.effective_from, h.effective_to, h.shares, h.quality, h.basis,
                   sd.external_id, s.code AS source_code
            FROM life360_holding_anchors h
            JOIN source_documents sd ON sd.id=h.source_document_id
            JOIN sources s ON s.id=sd.source_id
            """
        ).fetchone()
        assert row is not None
        assert row["effective_from"] == "2025-12-31"
        assert row["effective_to"] is None
        assert row["shares"] == 37_028
        assert row["quality"] == "DERIVED_HIGH_CONFIDENCE"
        assert row["basis"] == "DERIVED_FROM_2025_FAIR_VALUE"
        assert row["external_id"] == "otello-annual-2025"
        assert row["source_code"] == "OTELLO_IR"
    finally:
        d1.close()


def test_d1_migrations_do_not_take_over_wrangler_migration_tracking() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            D1_SCHEMA,
            D1_REFERENCE_DATA,
            D1_OPTION_LIABILITY,
            D1_BEMOBI_FACTS,
            D1_BEMOBI_WEB,
            D1_NORGES_BANK,
            D1_BEMOBI_CONSENSUS,
            D1_LIFE360,
            D1_LIFE360_IR_LSEG,
            D1_OTHER_SHARES,
            D1_LIFE360_HOLDINGS,
            D1_BROKER_MODEL,
        )
    ).upper()

    assert "SCHEMA_MIGRATIONS" not in combined
    assert "BEGIN TRANSACTION" not in combined
    assert "BEGIN IMMEDIATE" not in combined
    assert not re.search(r"(^|;)\s*COMMIT\s*;", combined)


def test_newsweb_safety_triggers_behave_the_same(tmp_path: Path) -> None:
    reference = _connect_reference(tmp_path)
    d1 = _connect_d1_shape()
    try:
        d1.executescript(D1_REFERENCE_DATA.read_text(encoding="utf-8"))
        for connection in (reference, d1):
            newsweb_id = connection.execute(
                "SELECT id FROM sources WHERE code = 'NEWSWEB'"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO source_documents(
                    source_id, external_id, document_type, title, url
                ) VALUES (?, 'parity-doc', 'REGULATORY_NEWS_MIRROR', 'Parity', 'https://example.test')
                """,
                (newsweb_id,),
            )
            row = connection.execute(
                "SELECT document_type FROM source_documents WHERE external_id = 'parity-doc'"
            ).fetchone()
            assert row[0] == "REGULATORY_NEWS"
            connection.rollback()
    finally:
        reference.close()
        d1.close()
