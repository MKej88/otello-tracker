from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from d1_preflight import run_d1_preflight  # noqa: E402

from app.db.connection import get_connection  # noqa: E402
from app.db.migration_runner import init_database  # noqa: E402
from app.history import seed_curated_history  # noqa: E402


class _SQLiteAsyncRepository:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    async def all(self, sql: str, parameters=()):
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        finally:
            connection.close()

    async def first(self, sql: str, parameters=()):
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None


def test_d1_preflight_blocks_test_fixture_source_documents(tmp_path: Path) -> None:
    database = str(tmp_path / "d1-fixture-guard.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        source_id = connection.execute("SELECT id FROM sources ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, url
            ) VALUES (?, 'd1-ci-production-guard', 'TEST_FIXTURE', 'fixture',
                      'https://example.test/fixture')
            """,
            (source_id,),
        )
        connection.commit()

    result = asyncio.run(
        run_d1_preflight(
            _SQLiteAsyncRepository(database),
            target_date="2026-08-18",
            check_derived=False,
        )
    )
    checks = {item["name"]: item for item in result["checks"]}

    assert checks["production_fixture_sentinel"]["status"] == "FAIL"
    assert checks["production_fixture_sentinel"]["details"]["fixture_markers"] == 1
    assert any(item["name"] == "production_fixture_sentinel" for item in result["blockers"])
    assert result["ready"] is False
