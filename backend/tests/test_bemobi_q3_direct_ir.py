"""Regressions: Bemobi 3Q26 is discoverable from issuer IR before CVM ZIP updates."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "cloudflare" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import bemobi_ir_news as ir  # noqa: E402
import bemobi_web_refresh as web  # noqa: E402


RELEASE_URL = (
    f"https://filemanager-cdn.mziq.com/published/{ir.COMPANY_ID}/"
    "q3-official-release"
)
Q3_TEXT = """
BEMOBI MOBILE TECH S.A.
Earnings Release 3Q26
Net Revenue grew 31% YoY to R$245.3 million.
Adjusted EBITDA grew 38% YoY to R$86.8 million.
Adjusted Net Income grew 20% YoY to R$51.0 million.
Adjusted EBITDA - Capex expanded 47% YoY to R$70.0 million.
Adjusted EBITDA Margin 35.4%
"""


class IssuerRepository:
    def __init__(self):
        self.documents = []
        self.writes = []
        self.snapshot = json.dumps({
            "checked_date": "2026-11-13",
            "rows": [{
                "id": "earnings-3q26",
                "date": "2026-11-12",
                "title": "Earnings Release 3Q26",
                "original_title": "Release de Resultados 3T26",
                "url": RELEASE_URL,
                "document_kind": "EARNINGS_RELEASE",
                "category": "release-de-resultados",
            }],
        })

    async def first(self, sql, parameters=()):
        if "FROM runtime_state" in sql:
            return {"value": self.snapshot}
        if "fact_type='RESULT'" in sql or "fact_type='NEXT_QUARTER'" in sql:
            return None
        raise AssertionError(sql)

    async def all(self, sql, parameters=()):
        assert "FROM company_news" in sql
        # CVM has not published the new IPE/ITR ZIP yet.
        return []

    async def create_source_document(self, **kwargs):
        self.documents.append(kwargs)
        return 77

    async def run(self, sql, parameters=()):
        self.writes.append((sql, parameters))


def test_q3_prose_parser_reads_amounts_not_growth_percentages():
    report = web.parse_bemobi_result_text(Q3_TEXT, published_date="2026-11-12")
    assert report["period"] == "3Q26"
    assert report["period_end"] == "2026-09-30"
    assert report["adjusted_net_revenue_mbrl"] == 245.3
    assert report["adjusted_ebitda_mbrl"] == 86.8
    assert report["adjusted_net_income_mbrl"] == 51.0
    assert report["ebitda_less_capex_mbrl"] == 70.0


def test_issuer_release_ingests_q3_even_when_cvm_has_no_new_document(monkeypatch):
    repo = IssuerRepository()

    async def fetch_pdf(url, *, fetcher=None):
        assert url == RELEASE_URL
        return b"%PDF-1.4 test", url, False

    monkeypatch.setattr(web, "_fetch_result_payload", fetch_pdf)
    monkeypatch.setattr(web, "_pdf_text", lambda _raw: Q3_TEXT)
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-13",
    ))
    assert result["status"] == "ok"
    assert result["period"] == "3Q26"
    assert repo.documents[0]["source_code"] == "BEMOBI_IR"
    assert repo.documents[0]["url"] == RELEASE_URL
    facts = {params[0] for sql, params in repo.writes
             if "INSERT INTO bemobi_investor_facts" in sql}
    assert {"RESULT", "TTM_QUARTER", "NEXT_QUARTER"} <= facts

    news, warning = asyncio.run(ir.official_ir_news(
        repo, target_date="2026-11-13",
    ))
    assert warning is None
    assert len(news) == 1
    assert news[0]["category"] == "RESULTS"
    assert news[0]["url"] == RELEASE_URL


def test_snapshot_rejects_unverified_or_future_issuer_release():
    repo = IssuerRepository()
    original = json.loads(repo.snapshot)
    original["rows"][0]["url"] = "https://evil.example/3q26.pdf"
    repo.snapshot = json.dumps(original)
    assert asyncio.run(web._official_ir_result_candidates(
        repo, target_date="2026-11-13"
    )) == []
    assert repo.documents == []

    original["rows"][0]["url"] = RELEASE_URL
    original["rows"][0]["date"] = "2026-11-15"
    repo.snapshot = json.dumps(original)
    assert asyncio.run(web._official_ir_result_candidates(
        repo, target_date="2026-11-13"
    )) == []
    assert repo.documents == []


def test_newer_cvm_report_is_not_masked_by_older_ir_release(monkeypatch):
    repo = IssuerRepository()
    old = json.loads(repo.snapshot)
    old["rows"][0]["date"] = "2026-08-11"
    old["rows"][0]["title"] = "Earnings Release 2Q26"
    repo.snapshot = json.dumps(old)

    async def cvm_rows(sql, parameters=()):
        assert "FROM company_news" in sql
        return [{
            "id": 88, "url": "https://www.rad.cvm.gov.br/release-3q26.pdf",
            "title": "Earnings Release 3Q26",
            "published_at": "2026-11-12T19:00:00Z",
            "source_code": "CVM",
        }]

    observed = []

    async def fetch_pdf(url, *, fetcher=None):
        observed.append(url)
        return b"%PDF-1.4 test", url, False

    repo.all = cvm_rows
    monkeypatch.setattr(web, "_fetch_result_payload", fetch_pdf)
    monkeypatch.setattr(web, "_pdf_text", lambda _raw: Q3_TEXT)
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-13",
    ))
    assert result["period"] == "3Q26"
    assert observed[0] == "https://www.rad.cvm.gov.br/release-3q26.pdf"
