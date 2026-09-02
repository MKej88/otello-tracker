from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = (
    ROOT / "backend" / "app" / "db" / "migrations" / "0033_patent_proceeds.sql",
    ROOT / "cloudflare" / "migrations" / "0030_patent_proceeds.sql",
)


@pytest.mark.parametrize("migration", MIGRATIONS, ids=("sqlite", "d1"))
def test_patent_proceeds_migration_uses_exact_prefix_without_like(
    migration: Path,
) -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE cash_movements (external_movement_id TEXT)")
    connection.executemany(
        "INSERT INTO cash_movements (external_movement_id) VALUES (?)",
        (
            ("otello-report-post-cash:PATENT_SALE_FINAL_INSTALMENT:2026-08-28",),
            ("otello-report-post-cash:PATENT-SALE-FINAL-INSTALMENT:2026-08-28",),
            ("unrelated",),
        ),
    )

    sql = migration.read_text(encoding="utf-8")
    assert " LIKE " not in sql.upper()
    connection.executescript(sql)

    rows = connection.execute(
        "SELECT external_movement_id, identified_type FROM cash_movements "
        "ORDER BY rowid"
    ).fetchall()
    assert rows == [
        (
            "otello-report-post-cash:PATENT_SALE_FINAL_INSTALMENT:2026-08-28",
            "PATENT_PROCEEDS",
        ),
        (
            "otello-report-post-cash:PATENT-SALE-FINAL-INSTALMENT:2026-08-28",
            None,
        ),
        ("unrelated", None),
    ]
