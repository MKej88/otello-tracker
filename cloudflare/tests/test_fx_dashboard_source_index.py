from __future__ import annotations

import asyncio
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from decimal import Decimal

from src.fx_dashboard import _preferred_series

ROOT = Path(__file__).resolve().parents[1]

# Original production query, kept independently as the parity reference.
ORIGINAL = """
SELECT substr(fr.observed_at, 1, 10) AS rate_date, fr.rate, s.code AS source_code
FROM fx_rates fr JOIN sources s ON s.id = fr.source_id
WHERE fr.base_currency = ? AND fr.quote_currency = 'NOK'
  AND s.code IN ('NORGES_BANK', 'ECB')
  AND substr(fr.observed_at, 1, 10) BETWEEN ? AND ?
  AND CAST(fr.rate AS REAL) > 0
ORDER BY rate_date,
  CASE s.code WHEN 'NORGES_BANK' THEN 0 WHEN 'ECB' THEN 1 ELSE 5 END,
  fr.observed_at DESC, fr.id DESC
"""


def test_source_first_series_preserves_financial_selection_and_uses_source_index():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript("""
        CREATE TABLE sources(id INTEGER PRIMARY KEY, code TEXT UNIQUE);
        CREATE TABLE fx_rates(
            id INTEGER PRIMARY KEY, base_currency TEXT NOT NULL,
            quote_currency TEXT NOT NULL, observed_at TEXT NOT NULL,
            rate TEXT NOT NULL, source_id INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(base_currency,quote_currency,observed_at,source_id)
        );
        CREATE INDEX idx_fx_rates_pair_time ON fx_rates(base_currency,quote_currency,observed_at);
        CREATE INDEX idx_fx_rates_pair_calendar_date
            ON fx_rates(base_currency, quote_currency, substr(observed_at,1,10), observed_at);
        INSERT INTO sources VALUES (1,'NORGES_BANK'), (2,'ECB'), (3,'EXCHANGERATE_DEV');
        """)
        db.executescript((ROOT / "migrations/0045_fx_coverage_indexes.sql").read_text(encoding="utf-8"))

        def insert(currency, observed, rate, source, quote="NOK"):
            db.execute(
                "INSERT INTO fx_rates(base_currency,quote_currency,observed_at,rate,source_id,fetched_at) VALUES (?,?,?,?,?,?)",
                (currency, quote, observed, rate, source, observed),
            )

        for i in range(3650):
            day = (date(2016, 1, 1) + timedelta(days=i)).isoformat()
            for currency in ("BRL", "USD"):
                for source in (1, 2, 3):
                    insert(currency, day + "T00:00:00Z", "1.5" if source == 1 else "1.6", source)
        # Source precedence, within-day order, rejected non-positive rate,
        # ECB fallback, excluded intraday and other quote currency.
        insert("BRL", "2025-12-20T12:00:00Z", "1.7", 1)
        insert("BRL", "2025-12-20T15:00:00Z", "0", 1)
        insert("BRL", "2025-12-20T18:00:00Z", "9", 2)
        insert("BRL", "2025-12-20T23:00:00Z", "99", 3)
        insert("BRL", "2025-12-20T23:00:00Z", "99", 1, quote="EUR")
        db.execute("DELETE FROM fx_rates WHERE base_currency='BRL' AND source_id=1 AND observed_at='2025-12-21T00:00:00Z'")

        def read(sql, params):
            steps = 0

            def count():
                nonlocal steps
                steps += 1
                return 0

            db.set_progress_handler(count, 1)
            try:
                return [dict(row) for row in db.execute(sql, params)], steps
            finally:
                db.set_progress_handler(None, 0)

        class Repository:
            async def all(self, sql, parameters=()):
                self.sql = sql
                self.rows, self.steps = read(sql, parameters)
                return self.rows

        for currency in ("BRL", "USD"):
            params = (currency, "2021-01-01", "2026-01-01")
            original, before = read(ORIGINAL, params)
            repo = Repository()
            series = asyncio.run(_preferred_series(
                repo, base_currency=currency, start_date=params[1], end_date=params[2]
            ))
            assert repo.rows == original
            expected = {}
            for row in original:
                expected.setdefault(row["rate_date"], {
                    "date": row["rate_date"], "rate": Decimal(row["rate"]),
                    "source_code": row["source_code"],
                })
            assert series == list(expected.values())
            assert repo.steps < before, (before, repo.steps)
            plan = " ".join(str(tuple(row)) for row in db.execute("EXPLAIN QUERY PLAN " + repo.sql, params))
            assert "idx_fx_coverage_date" in plan
            if currency == "BRL":
                assert expected["2025-12-20"]["rate"] == Decimal("1.7")
                assert expected["2025-12-21"]["source_code"] == "ECB"

        assert asyncio.run(_preferred_series(
            Repository(), base_currency="BRL", start_date="2090-01-01", end_date="2090-01-02"
        )) == []
    finally:
        db.close()
