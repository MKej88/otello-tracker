from __future__ import annotations

from pathlib import Path

from app.db.connection import get_connection

MIGRATIONS_DIR = Path(__file__).with_name("migrations")

CORE_TABLES = (
    "sources",
    "source_documents",
    "instruments",
    "market_prices",
    "fx_rates",
    "bemobi_holdings",
    "otello_share_counts",
    "cash_anchors",
    "cash_movements",
    "other_net_assets_anchors",
    "buyback_programs",
    "buybacks",
    "corporate_actions",
    "nav_snapshots",
    "broker_estimate_sets",
    "broker_estimate_values",
    "consensus_snapshots",
    "provenance_records",
    "job_runs",
    "source_health",
)


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def init_database(database_path: str | None = None) -> list[str]:
    applied: list[str] = []

    with get_connection(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        connection.commit()

        existing = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }

        for migration_file in _migration_files():
            version = migration_file.name.split("_", 1)[0]
            if version in existing:
                continue

            sql = migration_file.read_text(encoding="utf-8")
            safe_version = version.replace("'", "''")
            script = (
                "BEGIN IMMEDIATE;\n"
                + sql
                + f"\nINSERT INTO schema_migrations(version) VALUES ('{safe_version}');\n"
                + "COMMIT;\n"
            )

            try:
                connection.executescript(script)
            except Exception:
                connection.rollback()
                raise

            applied.append(version)
            existing.add(version)

    return applied


def database_status(database_path: str | None = None) -> dict:
    with get_connection(database_path) as connection:
        migration_row = connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()

        table_counts: dict[str, int] = {}
        for table in CORE_TABLES:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists:
                table_counts[table] = connection.execute(
                    f'SELECT COUNT(*) AS count FROM "{table}"'
                ).fetchone()["count"]

        return {
            "status": "ok",
            "latest_migration": migration_row["version"] if migration_row else None,
            "latest_migration_at": migration_row["applied_at"] if migration_row else None,
            "table_counts": table_counts,
        }
