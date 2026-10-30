from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db.migration_runner import init_database

ROOT = Path(__file__).resolve().parents[2]
SQLITE_MIGRATION = ROOT / "backend/app/db/migrations/0043_itau_safra_q3_previews.sql"
D1_MIGRATION = ROOT / "cloudflare/migrations/0041_itau_safra_q3_previews.sql"


def _load(connection: sqlite3.Connection) -> dict:
    return json.loads(
        connection.execute(
            "SELECT payload_json FROM bemobi_investor_facts "
            "WHERE fact_type='NEXT_QUARTER' AND fact_key='3Q26'"
        ).fetchone()[0]
    )


def test_new_public_broker_previews_are_source_attributed_and_repeatable(tmp_path):
    assert SQLITE_MIGRATION.read_text() == D1_MIGRATION.read_text()
    database = str(tmp_path / "quarter-2026.db")
    init_database(database)
    with sqlite3.connect(database) as connection:
        original = _load(connection)
        assert original["report_date"] == "2026-11-12"
        by_broker = {}
        for item in original["estimates"]:
            by_broker.setdefault(item["broker"], {})[item["metric"]] = item
        assert {"XP", "BTG Pactual", "Itaú BBA", "Safra"} <= set(by_broker)

        itau = by_broker["Itaú BBA"]
        safra = by_broker["Safra"]
        assert itau["revenue_mbrl"]["value_mbrl"] == 242
        assert itau["ebitda_margin_pct"]["value_pct"] == 34.4
        assert itau["adjusted_net_income_mbrl"]["value_mbrl"] == 52
        assert "adjusted_ebitda_mbrl" not in itau  # Estimated in UI with an asterisk.
        assert all(
            item["source_evidence"] == "OFFICIAL_BROKER_ARTICLE_VERIFIED"
            and "itau.com.br" in item["source_url"]
            and item.get("published_date") is None
            and item["verified_date"] == "2026-10-30"
            for item in itau.values()
        )
        assert safra["revenue_mbrl"]["value_mbrl"] == 231.9
        assert safra["adjusted_ebitda_mbrl"]["value_mbrl"] == 79.3
        assert safra["adjusted_net_income_mbrl"]["value_mbrl"] == 43.5
        assert "ebitda_margin_pct" not in safra  # Calculated in UI.
        assert all(
            item["published_date"] == "2026-10-23"
            and item["research_date"] == "2026-10-22"
            and item["source_evidence"] == "BROKER_PUBLISHED_SUMMARY"
            and "safra.com.br" in item["source_url"]
            for item in safra.values()
        )
        assert by_broker["XP"]["revenue_mbrl"]["value_mbrl"] == 239
        assert by_broker["BTG Pactual"]["revenue_mbrl"]["value_mbrl"] == 239.8
        connection.executescript(SQLITE_MIGRATION.read_text())
        again = _load(connection)
        assert len(again["estimates"]) == len(original["estimates"])
        assert again["estimates"] == original["estimates"]


def test_broker_previews_do_not_replace_existing_newer_broker_facts(tmp_path):
    database = str(tmp_path / "quarter-newer.db")
    init_database(database)
    with sqlite3.connect(database) as connection:
        modified = _load(connection)
        older_count = len(modified["estimates"])
        modified["estimates"].append(
            {"broker": "Morgan Stanley", "metric": "revenue_mbrl",
             "value_mbrl": 245, "published_date": "2026-10-28"}
        )
        connection.execute(
            "UPDATE bemobi_investor_facts SET payload_json=? "
            "WHERE fact_type='NEXT_QUARTER' AND fact_key='3Q26'",
            (json.dumps(modified),),
        )
        connection.executescript(SQLITE_MIGRATION.read_text())
        after = _load(connection)
        assert len(after["estimates"]) == older_count + 1
        assert after["estimates"] == modified["estimates"]
