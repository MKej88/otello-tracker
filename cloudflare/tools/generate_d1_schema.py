from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TARGET = ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"

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
        "-- Regenerate with: python cloudflare/tools/generate_d1_schema.py",
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

    parts.extend(
        [
            "PRAGMA defer_foreign_keys = OFF;",
            "PRAGMA optimize;",
            "",
        ]
    )
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the consolidated Cloudflare D1 schema.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed D1 schema differs from the generated reference schema.",
    )
    args = parser.parse_args()

    rendered = render_d1_schema()
    if args.check:
        if not TARGET.exists():
            print(f"Missing generated schema: {TARGET}", file=sys.stderr)
            return 1
        committed = TARGET.read_text(encoding="utf-8")
        if committed != rendered:
            print(
                "Cloudflare D1 schema is stale. Run: python cloudflare/tools/generate_d1_schema.py",
                file=sys.stderr,
            )
            return 1
        print("Cloudflare D1 schema matches the migrated SQLite reference schema.")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"Wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
