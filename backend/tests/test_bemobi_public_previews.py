from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

from app.db.migration_runner import init_database

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloudflare" / "src"))

import bemobi_public_previews as previews  # noqa: E402
from bemobi_web_refresh import parse_xp_preview_html  # noqa: E402

# Sanitized prose from the public BTG sector report dated 08.10.2026.
BTG_HTML = """
<h1>Telecom &amp; Tech - Prévia 3T26 (II)</h1><p>08/10/2026</p>
<h2>Intelbras: melhores tendências</h2><p>Projetamos EBITDA de R$ 169 milhões.</p>
<h2>Bemobi: mais um trimestre excepcional</h2>
<p>Projetamos crescimento de 28% a/a na receita consolidada, impulsionada por
Pagamentos, com alta de 64% a/a (ou fortes 24% excluindo a Paytime), e por SaaS,
com alta de 20% a/a. A margem EBITDA deve alcançar 35,7%, levando o EBITDA a
crescer 36% a/a. Por fim, projetamos cash lucro caixa de R$ 48 milhões no trimestre.</p>
<p>Tabela 3: Prévia do 3T26 da Bemobi</p><img src="table.png">
<h2>LWSA: macro deve pesar</h2><p>EBITDA de R$ 101 milhões.</p>
"""


class Repository:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""CREATE TABLE bemobi_investor_facts (
            id INTEGER PRIMARY KEY, fact_type TEXT, fact_key TEXT, as_of_date TEXT,
            published_date TEXT, payload_json TEXT, source_name TEXT, source_url TEXT,
            quality TEXT, notes TEXT, source_document_id INTEGER, updated_at TEXT,
            UNIQUE(fact_type, fact_key))""")
        self.connection.execute(
            """INSERT INTO bemobi_investor_facts
            (fact_type,fact_key,as_of_date,payload_json,source_name)
            VALUES ('NEXT_QUARTER','3Q26','2026-08-19',?,'Bemobi IR')""",
            (json.dumps({"report_date": "2026-11-12", "estimates": []}),),
        )

    async def run(self, sql, parameters=()):
        return self.connection.execute(sql, parameters)

    async def first(self, sql, parameters=()):
        row = self.connection.execute(sql, parameters).fetchone()
        return dict(row) if row else None

    async def create_source_document(self, **kwargs):
        return 1

    def payload(self):
        return json.loads(
            self.connection.execute(
                "SELECT payload_json FROM bemobi_investor_facts WHERE fact_type='NEXT_QUARTER'"
            ).fetchone()[0]
        )


def test_btg_sector_preview_keeps_units_and_cash_profit_definition():
    result = previews.parse_btg_preview_html(BTG_HTML)
    assert result["period"] == "3Q26"
    assert result["published_date"] == "2026-10-08"
    values = {item["metric"]: item for item in result["estimates"]}
    assert values["revenue_yoy_pct"]["value_pct"] == 28
    assert values["ebitda_yoy_pct"]["value_pct"] == 36
    assert values["ebitda_margin_pct"]["value_pct"] == 35.7
    assert values["cash_profit_mbrl"]["value_mbrl"] == 48
    assert "adjusted_net_income_mbrl" not in values
    assert "adjusted_ebitda_mbrl" not in values  # peers' 169/101 must not leak


def test_no_bemobi_section_or_invalid_margin_does_not_produce_preview():
    assert previews.parse_btg_preview_html(BTG_HTML.replace("Bemobi:", "Peer:")) is None
    assert previews.parse_btg_preview_html(BTG_HTML.replace("35,7%", "135,7%")) is None
    assert previews.parse_btg_preview_html(BTG_HTML.replace("08/10/2026", "")) is None


def test_xp_sector_preview_uses_bemobi_numbers_and_rejects_percentages():
    html = """<meta property="article:published_time" content="2026-10-09T12:00:00Z">
    <h1>TMT prévia 3Q26</h1><h2>Totvs: preview</h2>
    <p>EBITDA ajustado de R$ 501 milhões e lucro líquido ajustado de R$ 200 milhões.</p>
    <h2>Bemobi: preview</h2><p>Receita líquida de R$ 250 milhões,
    EBITDA ajustado de R$ 86 milhões e lucro líquido ajustado de R$ 49 milhões.</p>
    <h2>LWSA: preview</h2><p>EBITDA ajustado de R$ 101 milhões.</p>"""
    parsed = parse_xp_preview_html(html)
    assert [item["value_mbrl"] for item in parsed["estimates"]] == [250, 86, 49]
    assert parse_xp_preview_html(html.replace("R$ 86 milhões", "36%")) is None


def test_preserves_other_brokers_report_date_and_newer_publications():
    repository = Repository()

    async def write(broker, publication, value):
        latest = await repository.first(
            "SELECT fact_key,payload_json FROM bemobi_investor_facts"
        )
        return await previews.store_public_preview(
            repository,
            latest=latest,
            broker=broker,
            url="https://example.test/preview",
            preview={
                "period": "3Q26",
                "published_date": publication,
                "estimates": [
                    {
                        "metric": "cash_profit_mbrl",
                        "label": "Cash profit",
                        "value_mbrl": value,
                    }
                ],
            },
            document_id=1,
            target_date="2026-10-10",
        )

    assert asyncio.run(write("XP", "2026-10-09", 49))
    assert asyncio.run(write("BTG Pactual", "2026-10-08", 48))
    assert not asyncio.run(write("XP", "2026-10-07", 42))
    assert not asyncio.run(write("XP", "2026-10-11", 55))
    payload = repository.payload()
    assert payload["report_date"] == "2026-11-12"
    assert {item["broker"]: item["value_mbrl"] for item in payload["estimates"]} == {
        "XP": 49,
        "BTG Pactual": 48,
    }


def test_daily_q3_discovery_accepts_sector_title_and_stops_after_result():
    repository = Repository()
    calls = []

    class Response:
        status = 200
        ok = True

        def __init__(self, payload):
            self.payload = payload.encode()

        async def arrayBuffer(self):
            return self.payload

    async def fetch(url, **kwargs):
        calls.append(url)
        if url == previews.BTG_INDEX_URL:
            return Response(
                '<a href="/research/home/relatorio/new/Telecom-Tech-Previa-3T26-II">TMT Prévia 3T26</a>'
            )
        if urlparse(url).hostname == "content.btgpactual.com":
            return Response(BTG_HTML)
        return Response("<h1>No public XP preview yet</h1>")

    for day in ("2026-10-09", "2026-10-10"):
        result = asyncio.run(
            previews.sync_q3_previews(repository, target_date=day, fetcher=fetch)
        )
        assert result["btg_preview"]["status"] == "ok"
        assert repository.payload()["estimates"][0]["broker"] == "BTG Pactual"
    assert calls.count(previews.BTG_INDEX_URL) == 2
    assert any("/relatorio/new/" in url for url in calls)
    repository.connection.execute(
        "INSERT INTO bemobi_investor_facts(fact_type,fact_key) VALUES ('RESULT','3Q26')"
    )
    calls.clear()
    result = asyncio.run(
        previews.sync_q3_previews(repository, target_date="2026-11-13", fetcher=fetch)
    )
    assert result["reason"] == "q3_watch_not_pending"
    assert calls == []


def test_migration_keeps_existing_estimates_and_is_repeatable():
    backend = (ROOT / "backend/app/db/migrations/0038_btg_q3_preview.sql").read_text()
    assert (
        backend == (ROOT / "cloudflare/migrations/0035_btg_q3_preview.sql").read_text()
    )
    repository = Repository()
    repository.connection.execute(
        "CREATE TABLE sources(code TEXT PRIMARY KEY,name TEXT,source_type TEXT,base_url TEXT,is_official INT,terms_notes TEXT)"
    )
    payload = {
        "report_date": "2026-11-12",
        "estimates": [{"broker": "XP", "value_mbrl": 50}],
    }
    repository.connection.execute(
        "UPDATE bemobi_investor_facts SET payload_json=?", (json.dumps(payload),)
    )
    repository.connection.executescript(backend)
    repository.connection.executescript(backend)
    result = repository.payload()
    assert result["report_date"] == "2026-11-12"
    assert len(result["estimates"]) == 5
    assert result["estimates"][0]["broker"] == "XP"
    assert result["estimates"][1]["value_pct"] == 28


def test_btg_preview_is_available_after_full_schema_migration(tmp_path):
    database_path = str(tmp_path / "bemobi.db")
    init_database(database_path)
    connection = sqlite3.connect(database_path)
    row = connection.execute(
        "SELECT payload_json FROM bemobi_investor_facts WHERE fact_type='NEXT_QUARTER' AND fact_key='3Q26'"
    ).fetchone()
    payload = json.loads(row[0])
    assert payload["status"] == "PUBLIC_ESTIMATES_AVAILABLE"
    assert payload["estimates"][0]["broker"] == "BTG Pactual"
    assert payload["estimates"][-1]["value_mbrl"] == 48
