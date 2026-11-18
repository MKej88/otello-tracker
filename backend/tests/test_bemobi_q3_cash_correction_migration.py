"""Regression: one-off production cash correction must be narrow and idempotent."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "cloudflare" / "migrations" / "0042_fix_bemobi_3q26_cash.sql"
)


def test_bemobi_q3_cash_one_time_migration_repairs_only_verified_source_row():
    con = sqlite3.connect(":memory:")
    con.execute("""
        CREATE TABLE bemobi_investor_facts (
            id INTEGER PRIMARY KEY,
            fact_type TEXT,
            fact_key TEXT,
            as_of_date TEXT,
            source_name TEXT,
            payload_json TEXT,
            updated_at TEXT
        )
    """)

    def row(period, cash, *, source="BEMOBI_IR", revenue=245.0, ebitda=87.0):
        return (
            "RESULT", period, "2026-09-30" if period == "3Q26" else "2026-06-30",
            source, json.dumps({
                "period": period, "cash_mbrl": cash,
                "adjusted_net_revenue_mbrl": revenue,
                "adjusted_ebitda_mbrl": ebitda,
                "adjusted_net_income_mbrl": 51.0,
            }),
        )

    rows = [
        row("3Q26", 2025.0),
        row("2Q26", 2025.0),
        row("3Q26", 319.0),
        row("3Q26", 2025.0, source="UNVERIFIED"),
        row("3Q26", 2025.0, revenue=200.0),
        row("3Q26", 2025.0, ebitda=79.0),
    ]
    con.executemany(
        """INSERT INTO bemobi_investor_facts (
            fact_type, fact_key, as_of_date, source_name, payload_json
        ) VALUES (?, ?, ?, ?, ?)""", rows,
    )
    before = [
        json.loads(r[0]) for r in con.execute(
            "SELECT payload_json FROM bemobi_investor_facts ORDER BY id"
        )
    ]

    sql = MIGRATION.read_text(encoding="utf8")
    con.executescript(sql)
    after = [
        json.loads(r[0]) for r in con.execute(
            "SELECT payload_json FROM bemobi_investor_facts ORDER BY id"
        )
    ]
    assert after[0]["cash_mbrl"] == 319.0
    assert after[0]["cash_quality"] == "OFFICIAL_REPORTED"
    assert after[0]["cash_correction_source_url"].startswith("https://")
    assert after[0]["adjusted_net_income_mbrl"] == 51.0
    assert after[1:] == before[1:]

    con.executescript(sql)
    repeated = [
        json.loads(r[0]) for r in con.execute(
            "SELECT payload_json FROM bemobi_investor_facts ORDER BY id"
        )
    ]
    assert repeated == after
