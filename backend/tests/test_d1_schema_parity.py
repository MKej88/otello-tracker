from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.db.migration_runner import init_database


ROOT = Path(__file__).resolve().parents[2]
D1_SCHEMA = ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"
D1_REFERENCE_DATA = ROOT / "cloudflare" / "migrations" / "0002_reference_data.sql"
D1_OPTION_LIABILITY = ROOT / "cloudflare" / "migrations" / "0004_option_liability.sql"


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


def test_d1_migrations_do_not_take_over_wrangler_migration_tracking() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (D1_SCHEMA, D1_REFERENCE_DATA, D1_OPTION_LIABILITY)
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
