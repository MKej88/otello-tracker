from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import bemobi_web_refresh_runtime as web_refresh  # noqa: E402


class _FactRepository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("""
            CREATE TABLE bemobi_investor_facts (
                id INTEGER PRIMARY KEY,
                fact_type TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                as_of_date TEXT,
                published_date TEXT,
                payload_json TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT,
                quality TEXT NOT NULL,
                notes TEXT,
                source_document_id INTEGER,
                updated_at TEXT,
                UNIQUE (fact_type, fact_key)
            )
            """)

    async def run(self, sql: str, parameters=()):
        return self.connection.execute(sql, parameters)


def test_older_consensus_refresh_does_not_delete_newer_forecast(
    monkeypatch,
) -> None:
    repository = _FactRepository()
    repository.connection.execute("""
        INSERT INTO bemobi_investor_facts(
            fact_type, fact_key, as_of_date, payload_json, source_name, quality
        ) VALUES ('FORWARD_CONSENSUS', '2028', '2026-08-30', '{}',
                  'MarketScreener', 'PUBLIC_AGGREGATE_AUTO')
        """)

    async def fake_fetch(*args, **kwargs) -> bytes:
        return b"eldre konsensus"

    async def fake_store_document(*args, **kwargs) -> int:
        return 12

    async def fake_store_snapshot(*args, **kwargs) -> int:
        return 1

    monkeypatch.setattr(web_refresh, "_fetch_bytes", fake_fetch)
    monkeypatch.setattr(web_refresh, "_decode_html", lambda raw: raw.decode())
    monkeypatch.setattr(
        web_refresh,
        "parse_forward_consensus_html",
        lambda html, as_of_year: [{"year": 2027, "revenue_musd": 100}],
    )
    monkeypatch.setattr(web_refresh, "_store_web_document", fake_store_document)
    monkeypatch.setattr(web_refresh, "_store_forward_snapshot", fake_store_snapshot)

    result = asyncio.run(
        web_refresh.sync_marketscreener_consensus(
            repository,
            target_date="2026-08-20",
        )
    )

    rows = repository.connection.execute("""
        SELECT fact_key, as_of_date
        FROM bemobi_investor_facts
        WHERE fact_type='FORWARD_CONSENSUS'
        ORDER BY fact_key
        """).fetchall()
    assert result["status"] == "ok"
    assert rows == [("2027", "2026-08-20"), ("2028", "2026-08-30")]
