from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database


ROOT = Path(__file__).resolve().parents[2]


def test_bemobi_investor_facts_are_seeded_with_provenance(tmp_path: Path) -> None:
    database = str(tmp_path / "bemobi-facts.db")
    applied = init_database(database)

    assert applied[-1] == "0021"

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT fact_type, fact_key, as_of_date, published_date, payload_json,
                   source_name, source_url, quality, source_document_id
            FROM bemobi_investor_facts
            ORDER BY id
            """
        ).fetchall()

    assert len(rows) == 18
    counts = Counter(row["fact_type"] for row in rows)
    assert counts == {
        "RESULT": 1,
        "OWNERSHIP": 1,
        "TTM_QUARTER": 4,
        "VALUATION_ANCHOR": 1,
        "ANALYST": 4,
        "FORWARD_CONSENSUS": 2,
        "BEAT_MISS": 3,
        "REFERENCE_MODEL": 1,
        "NEXT_QUARTER": 1,
    }

    for row in rows:
        payload = json.loads(row["payload_json"])
        assert isinstance(payload, dict)
        assert row["source_name"]
        assert str(row["source_url"]).startswith("https://")
        assert row["quality"]
        assert row["source_document_id"] is None  # seed; future automatic refreshes attach web snapshots

    result = next(row for row in rows if row["fact_type"] == "RESULT")
    result_payload = json.loads(result["payload_json"])
    assert result["fact_key"] == "2Q26"
    assert result_payload["adjusted_ebitda_mbrl"] == 79.4
    assert result_payload["adjusted_net_income_mbrl"] == 45.2

    ownership = next(row for row in rows if row["fact_type"] == "OWNERSHIP")
    ownership_payload = json.loads(ownership["payload_json"])
    assert ownership_payload["shares"] == 32_719_588
    assert ownership_payload["ownership_pct"] == 38.22


def test_sqlite_and_d1_bemobi_reference_seeds_are_identical() -> None:
    sqlite_seed = (ROOT / "backend/app/db/migrations/0019_bemobi_investor_facts.sql").read_text(
        encoding="utf-8"
    )
    d1_seed = (ROOT / "cloudflare/migrations/0009_bemobi_investor_facts.sql").read_text(
        encoding="utf-8"
    )

    assert sqlite_seed == d1_seed
    assert "bemobi_investor_facts" in sqlite_seed
    assert "0018" not in sqlite_seed
    assert "shareholder" not in sqlite_seed.lower()
