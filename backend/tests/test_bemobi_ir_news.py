import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

from app.db.migration_runner import init_database

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloudflare/src"))
import bemobi_ir_news as ir  # noqa: E402


def row(**overrides):
    return dict(id="filing-1", company_id=ir.COMPANY_ID, is_published=True,
                file_published_date="2026-10-14T00:00:00Z", internal_name="comunicados",
                file_title="Notice to the Market - Statement of Disposal of a Significant Equity Interest",
                file_name_original="Comunicado ao Mercado - Declaração de Alienação de Participação Acionária Relevante",
                file_url=ir.BOOTSTRAP_ROWS[0]["url"], **overrides)


def payload(rows):
    return dict(success=True, data=dict(document_metas=rows))


class Repository:
    def __init__(self):
        self.value = None

    async def first(self, query, parameters=()):
        return dict(value=self.value) if self.value is not None else None

    async def run(self, query, parameters=()):
        self.value = parameters[1]


def test_parser_preserves_dates_links_and_rejects_untrusted_documents():
    parsed = ir.parse_ir_filings(payload([row(), row()]), target_date="2026-10-17")
    assert len(parsed) == 1
    assert parsed[0]["date"] == "2026-10-14"
    assert parsed[0]["url"] == ir.BOOTSTRAP_ROWS[0]["url"]
    for field, value in [("company_id", "someone-else"), ("file_url", "https://evil.test/document")]:
        bad = row(); bad[field] = value
        with pytest.raises(ValueError):
            ir.parse_ir_filings(payload([bad]), target_date="2026-10-17")
    future = row(); future["file_published_date"] = "2026-10-18"
    assert ir.parse_ir_filings(payload([future]), target_date="2026-10-17") == []
    with pytest.raises(ValueError):
        ir.parse_ir_filings({}, target_date="2026-10-17")


def test_start_snapshot_is_date_gated_and_live_empty_snapshot_wins():
    repository = Repository()
    assert asyncio.run(ir.official_ir_news(repository, target_date="2026-10-16")) == ([], None)
    items, warning = asyncio.run(ir.official_ir_news(repository, target_date="2026-10-17"))
    assert len(items) == 1 and warning is None
    assert items[0]["published_at"] == "2026-10-14"
    assert items[0]["nav_impact"] == "NONE"
    repository.value = json.dumps(dict(checked_date="2026-10-17", rows=[]))
    assert asyncio.run(ir.official_ir_news(repository, target_date="2026-10-17")) == ([], None)
    assert "forsinket" in asyncio.run(ir.official_ir_news(repository, target_date="2026-10-20"))[1]


def test_official_post_refresh_and_failure_preserve_last_good():
    repository = Repository()
    calls = []

    class Response:
        ok = True
        async def text(self):
            return json.dumps(payload([row()]))

    async def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    result = asyncio.run(ir.refresh_ir_news(repository, target_date="2026-10-17", fetcher=fetch))
    assert result["status"] == "ok" and result["documents"] == 1
    assert calls[0][0] == ir.FEED_URL and calls[0][1]["method"] == "POST"
    assert json.loads(calls[0][1]["body"])["year"] == 2026
    before = copy.copy(repository.value)

    async def broken(*args, **kwargs):
        raise RuntimeError("HTTP 403")

    result = asyncio.run(ir.refresh_ir_news(repository, target_date="2026-10-18", fetcher=broken))
    assert result["status"] == "not_available" and repository.value == before


def test_cvm_ir_equivalent_ownership_titles_have_same_identity():
    assert ir.filing_key(row()["file_name_original"], "2026-10-14") == ir.filing_key(
        "Aquisição/Alienação de Participação Acionária Relevante", "2026-10-14T19:50:00Z")
    assert ir.filing_key("Incorporação 7AZ", "2026-09-30") == ir.filing_key(
        "Fato Relevante - Incorporação 7AZ.", "2026-09-30")
    assert ir.filing_key("Incorporação 7AZ", "2026-09-30") != ir.filing_key("Incorporação 7AZ", "2026-08-27")


def test_live_news_merge_keeps_cvm_priority_without_duplicate(tmp_path):
    import sqlite3
    from news_events import news_and_events
    path = str(tmp_path / "news.db")
    init_database(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row

    class SQLRepository:
        async def first(self, query, parameters=()):
            result = connection.execute(query, parameters).fetchone()
            return dict(result) if result else None
        async def all(self, query, parameters=()):
            return [dict(item) for item in connection.execute(query, parameters)]

    repository = SQLRepository()
    result = asyncio.run(news_and_events(repository, as_of_date="2026-10-17"))
    assert len(result["news"]) == 1
    assert result["news"][0]["source"] == "Bemobi IR"
    source = connection.execute("SELECT id FROM sources WHERE code='CVM'").fetchone()[0]
    issuer = connection.execute("SELECT id FROM instruments WHERE symbol='BMOB3'").fetchone()[0]
    subject = "Aquisição/Alienação de Participação Acionária Relevante"
    document = connection.execute("INSERT INTO source_documents(source_id,document_type,title,published_at,url,metadata_json) VALUES (?,?,?,?,?,?)",
        (source,"CVM_IPE_METADATA",subject,"2026-10-14","https://www.rad.cvm.gov.br/filing",json.dumps(dict(cvm_subject=subject)))).lastrowid
    connection.execute("INSERT INTO company_news(issuer_instrument_id,source_document_id,headline,published_at,category,nav_impact,processing_status) VALUES (?,?,?,?,?,?,?)",
        (issuer,document,subject,"2026-10-14","CORPORATE","NONE","PARSED"))
    result = asyncio.run(news_and_events(repository, as_of_date="2026-10-17"))
    assert len(result["news"]) == 1
    assert result["news"][0]["source"] != "Bemobi IR"
    connection.close()
