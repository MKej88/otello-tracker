from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "cloudflare" / "src" / "bemobi_source_status.py"
SPEC = importlib.util.spec_from_file_location("worker_status_query", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
worker_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker_module
SPEC.loader.exec_module(worker_module)


class _SqliteRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.queries = 0

    async def all(self, sql: str, parameters: tuple = ()) -> list[dict]:
        self.queries += 1
        return [dict(row) for row in self.connection.execute(sql, parameters)]


def test_latest_facts_use_one_query_and_preserve_source_filter() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE bemobi_investor_facts (
               id INTEGER PRIMARY KEY, fact_type TEXT, fact_key TEXT,
               as_of_date TEXT, published_date TEXT, source_name TEXT,
               source_url TEXT, quality TEXT, updated_at TEXT
           )""")
    connection.executemany(
        "INSERT INTO bemobi_investor_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1,
                "OWNERSHIP",
                "old",
                "2026-01-01",
                None,
                "IR",
                "old",
                "OK",
                "2026-01-01",
            ),
            (2, "ANALYST", "new", "2026-06-01", None, "IR", "new", "OK", "2026-06-01"),
            (
                3,
                "NEXT_QUARTER",
                "wrong",
                "2026-09-01",
                None,
                "BTG",
                "wrong",
                "OK",
                "2026-09-01",
            ),
            (
                4,
                "NEXT_QUARTER",
                "xp",
                "2026-08-01",
                None,
                "XP",
                "xp",
                "OK",
                "2026-08-01",
            ),
        ],
    )
    repository = _SqliteRepository(connection)

    facts = asyncio.run(worker_module._latest_facts(repository))

    assert repository.queries == 1
    assert facts["ir"]["fact_key"] == "new"
    assert facts["xp_preview"]["fact_key"] == "xp"
