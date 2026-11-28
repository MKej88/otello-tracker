from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from src.fx_freshness import norges_bank_fx_coverage

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_SQL = """
SELECT fr.base_currency, MAX(substr(fr.observed_at,1,10)) AS latest_date,
       MAX(fr.fetched_at) AS latest_fetch
FROM fx_rates fr JOIN sources s ON s.id=fr.source_id
WHERE fr.quote_currency='NOK' AND fr.base_currency IN ('BRL','USD')
  AND s.code='NORGES_BANK'
GROUP BY fr.base_currency ORDER BY fr.base_currency
"""


class Repository:
    def __init__(self, db):
        self.db = db
        self.sql = None

    async def all(self, sql, params=()):
        self.sql = sql
        return [dict(row) for row in self.db.execute(sql, params)]


def test_indexed_fx_coverage_matches_full_history_and_bounds_query_work():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript("""
        CREATE TABLE sources(id INTEGER PRIMARY KEY, code TEXT UNIQUE);
        CREATE TABLE fx_rates(
            id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL,
            base_currency TEXT NOT NULL, quote_currency TEXT NOT NULL,
            observed_at TEXT NOT NULL, fetched_at TEXT NOT NULL
        );
        CREATE INDEX idx_fx_rates_pair_calendar_date
            ON fx_rates(base_currency, quote_currency, substr(observed_at,1,10), observed_at);
        INSERT INTO sources VALUES (1,'NORGES_BANK'), (2,'EXCHANGERATE_DEV');
        """)
        db.executescript((ROOT / "migrations/0045_fx_coverage_indexes.sql").read_text(encoding="utf-8"))
        repo = Repository(db)
        assert asyncio.run(norges_bank_fx_coverage(repo)) == {
            "pairs": {}, "latest_common_date": None, "currency_count": 0,
        }

        # Older observation with a newer fetch time must remain the maximum fetch.
        # Competing sources and non-NOK rates must not enter coverage.
        rows = [
            (1, currency, "NOK",
             f"{2000 + i // 365:04d}-{1 + i % 12:02d}-{1 + i % 28:02d}T00:00:00Z",
             f"{2020 + i % 6}-01-01")
            for currency in ("BRL", "USD") for i in range(5000)
        ]
        db.executemany(
            "INSERT INTO fx_rates(source_id,base_currency,quote_currency,observed_at,fetched_at) VALUES (?,?,?,?,?)",
            rows + [
                (1, "BRL", "NOK", "1999-01-01T00:00:00Z", "2026-11-28T12:00:00Z"),
                (2, "BRL", "NOK", "2099-01-01T00:00:00Z", "2099-01-01"),
                (1, "USD", "EUR", "2099-01-01T00:00:00Z", "2099-01-01"),
            ],
        )

        def execute_with_steps(sql):
            steps = 0

            def count():
                nonlocal steps
                steps += 1
                return 0

            db.set_progress_handler(count, 1)
            try:
                return [dict(row) for row in db.execute(sql)], steps
            finally:
                db.set_progress_handler(None, 0)

        expected, before = execute_with_steps(ORIGINAL_SQL)
        actual = asyncio.run(norges_bank_fx_coverage(repo))
        indexed, after = execute_with_steps(repo.sql)
        assert indexed == expected
        assert actual["pairs"]["BRL/NOK"]["latest_fetch"] == "2026-11-28T12:00:00Z"
        assert actual["latest_common_date"] == min(row["latest_date"] for row in expected)
        assert after * 20 < before, (before, after)
        plan = " ".join(str(tuple(row)) for row in db.execute("EXPLAIN QUERY PLAN " + repo.sql))
        assert "idx_fx_coverage_date" in plan
        assert "idx_fx_coverage_fetch" in plan

        db.execute("DELETE FROM fx_rates WHERE base_currency='USD'")
        one = asyncio.run(norges_bank_fx_coverage(repo))
        assert one["currency_count"] == 1
        assert one["latest_common_date"] is None
        assert set(one["pairs"]) == {"BRL/NOK"}

        db.execute("DELETE FROM sources WHERE code='NORGES_BANK'")
        assert asyncio.run(norges_bank_fx_coverage(repo))["pairs"] == {}
    finally:
        db.close()
