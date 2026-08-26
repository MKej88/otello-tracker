from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
MIGRATIONS = ROOT / "cloudflare" / "migrations"
TARGET = MIGRATIONS / "0001_initial_schema.sql"
ADDITIVE_SCHEMA_MIGRATIONS = (
    MIGRATIONS / "0004_option_liability.sql",
    MIGRATIONS / "0009_bemobi_investor_facts.sql",
    MIGRATIONS / "0010_bemobi_web_provenance.sql",
    MIGRATIONS / "0012_bemobi_consensus_history.sql",
    MIGRATIONS / "0016_other_shares_and_life360_report_anchor.sql",
    MIGRATIONS / "0017_life360_holding_anchors.sql",
)

sys.path.insert(0, str(BACKEND))

from app.db.migration_runner import init_database  # noqa: E402


EXCLUDED_OBJECTS = {"schema_migrations"}
TYPE_ORDER = {"table": 0, "index": 1, "trigger": 2, "view": 3}


def _schema_objects(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE sql IS NOT NULL
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return sorted(
        (row for row in rows if row["name"] not in EXCLUDED_OBJECTS),
        key=lambda row: (TYPE_ORDER.get(row["type"], 9), row["name"]),
    )


def render_d1_schema() -> str:
    """Render a consolidated schema for a brand-new database.

    Once additive D1 migrations exist, this is a diagnostic/bootstrap aid only. Existing
    D1 databases must advance through the numbered additive migrations instead of
    rewriting migration 0001.
    """
    with tempfile.TemporaryDirectory(prefix="otello-d1-schema-") as temp_dir:
        database_path = str(Path(temp_dir) / "reference.db")
        init_database(database_path)
        connection = sqlite3.connect(database_path)
        try:
            objects = _schema_objects(connection)
        finally:
            connection.close()

    parts = [
        "-- GENERATED FILE. Do not edit by hand.",
        "-- Source: backend/app/db/migrations after the latest applied migration.",
        "-- D1 enforces foreign keys; defer checks while the empty schema is created.",
        "PRAGMA defer_foreign_keys = ON;",
        "",
    ]

    current_type: str | None = None
    for row in objects:
        object_type = str(row["type"])
        if object_type != current_type:
            if current_type is not None:
                parts.append("")
            parts.append(f"-- {object_type.upper()}S")
            current_type = object_type
        sql = str(row["sql"]).strip().rstrip(";")
        parts.extend((sql + ";", ""))

    parts.extend(["PRAGMA defer_foreign_keys = OFF;", "PRAGMA optimize;", ""])
    return "\n".join(parts)


def _connect_reference() -> sqlite3.Connection:
    temp = tempfile.NamedTemporaryFile(prefix="otello-schema-reference-", suffix=".db", delete=False)
    temp.close()
    init_database(temp.name)
    connection = sqlite3.connect(temp.name)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _connect_d1_chain() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(TARGET.read_text(encoding="utf-8"))
    for migration in ADDITIVE_SCHEMA_MIGRATIONS:
        if migration.exists():
            connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


def _tables(connection: sqlite3.Connection) -> list[str]:
    return [
        row["name"]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations'
            ORDER BY name
            """
        )
    ]


def _columns(connection: sqlite3.Connection, table: str) -> list[tuple]:
    return [
        (row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"])
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    ]


def _foreign_keys(connection: sqlite3.Connection, table: str) -> list[tuple]:
    return sorted(tuple(row) for row in connection.execute(f'PRAGMA foreign_key_list("{table}")'))


def _indexes(connection: sqlite3.Connection, table: str) -> dict[str, tuple]:
    result: dict[str, tuple] = {}
    for row in connection.execute(f'PRAGMA index_list("{table}")'):
        if row["origin"] != "c":
            continue
        result[row["name"]] = (
            row["unique"],
            row["partial"],
            tuple(
                item["name"]
                for item in connection.execute(f'PRAGMA index_info("{row["name"]}")')
            ),
        )
    return result


def _triggers(connection: sqlite3.Connection) -> dict[str, str]:
    import re

    return {
        row["name"]: re.sub(r"\s+", " ", row["sql"].strip()).rstrip(";")
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        )
    }


def check_schema_chain() -> list[str]:
    reference = _connect_reference()
    d1 = _connect_d1_chain()
    errors: list[str] = []
    try:
        reference_tables = _tables(reference)
        d1_tables = _tables(d1)
        if reference_tables != d1_tables:
            errors.append(f"table set mismatch: SQLite={reference_tables!r} D1={d1_tables!r}")
            return errors
        for table in reference_tables:
            if _columns(reference, table) != _columns(d1, table):
                errors.append(f"column mismatch: {table}")
            if _foreign_keys(reference, table) != _foreign_keys(d1, table):
                errors.append(f"foreign-key mismatch: {table}")
            if _indexes(reference, table) != _indexes(d1, table):
                errors.append(f"index mismatch: {table}")
        if _triggers(reference) != _triggers(d1):
            errors.append("trigger mismatch")
    finally:
        reference.close()
        d1.close()
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or validate the Cloudflare D1 schema.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate frozen 0001 plus additive schema migrations against latest SQLite.",
    )
    parser.add_argument(
        "--force-consolidate",
        action="store_true",
        help="Rewrite migration 0001 as a consolidated fresh-database schema. Never use after remote go-live.",
    )
    args = parser.parse_args()

    if args.check:
        if not TARGET.exists():
            print(f"Missing D1 baseline schema: {TARGET}", file=sys.stderr)
            return 1
        errors = check_schema_chain()
        if errors:
            print("Cloudflare D1 schema chain has drift:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print("Cloudflare D1 baseline + additive migrations match SQLite reference schema.")
        return 0

    if not args.force_consolidate:
        print(
            "Refusing to rewrite frozen D1 migration 0001. Use --force-consolidate only for a fresh pre-go-live baseline.",
            file=sys.stderr,
        )
        return 2

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render_d1_schema(), encoding="utf-8")
    print(f"Wrote consolidated fresh-database schema to {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
