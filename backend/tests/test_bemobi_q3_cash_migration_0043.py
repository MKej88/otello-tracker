"""Regression: 0043 fixes the unmatched 3Q26 row left by migration 0042."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


MIGRATIONS = Path(__file__).resolve().parents[2] / "cloudflare" / "migrations"


def test_q3_cash_repair_handles_real_world_provenance_and_never_changes_valid_cash():
    con = sqlite3.connect(":memory:")
    con.execute("""
        CREATE TABLE bemobi_investor_facts (
            id INTEGER PRIMARY KEY,
            fact_type TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            as_of_date TEXT,
            source_name TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT
        )
    """)

    def add(period: str, cash: float | None, *, source="Bemobi IR", as_of=None,
            fact_type="RESULT", fact_key=None):
        payload = {
            "period": period, "cash_mbrl": cash,
            "adjusted_net_revenue_mbrl": 245.0,
            "adjusted_ebitda_mbrl": 87.0,
            "adjusted_net_income_mbrl": 51.0,
        }
        con.execute(
            """INSERT INTO bemobi_investor_facts
               (fact_type, fact_key, as_of_date, source_name, payload_json)
               VALUES (?, ?, ?, ?, ?)""",
            (fact_type, fact_key or period, as_of, source, json.dumps(payload)),
        )

    add("3Q26", 2025.0, source="Bemobi IR", as_of="2026-09-30")
    add("3Q26", 2025.0, source="Different Official Publisher", as_of=None,
        fact_key="2026-09-30")
    add("3Q26", None, source="CVM", as_of="2026-09-30")
    add("3Q26", 319.3, as_of="2026-09-30")
    add("3Q26", 319.0, as_of="2026-09-30")
    add("2Q26", 2025.0, as_of="2026-06-30")
    add("3Q25", 2025.0, as_of="2025-09-30")
    add("3Q26", 2025.0, fact_type="OWNERSHIP")
    originals = [
        json.loads(row[0]) for row in con.execute(
            "SELECT payload_json FROM bemobi_investor_facts ORDER BY id"
        )
    ]

    sql = (MIGRATIONS / "0043_repair_bemobi_3q26_cash_unmatched.sql").read_text()
    con.executescript(sql)
    resulting = [
        json.loads(row[0]) for row in con.execute(
            "SELECT payload_json FROM bemobi_investor_facts ORDER BY id"
        )
    ]
    for index in (0, 1, 2):
        assert resulting[index]["cash_mbrl"] == 319.0
        assert resulting[index]["cash_quality"] == "OFFICIAL_REPORTED"
        assert "cash_correction_source_url" in resulting[index]
    assert resulting[3]["cash_mbrl"] == 319.3
    assert resulting[4]["cash_mbrl"] == 319.0
    assert resulting[5:] == originals[5:]
    assert all(row["adjusted_net_revenue_mbrl"] == 245 for row in resulting)

    con.executescript(sql)
    rerun = [
        json.loads(row[0]) for row in con.execute(
            "SELECT payload_json FROM bemobi_investor_facts ORDER BY id"
        )
    ]
    assert resulting == rerun
