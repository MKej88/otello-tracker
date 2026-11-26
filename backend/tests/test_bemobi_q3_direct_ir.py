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
    assert report["adjusted_ebitda_margin_pct"] == 35.4


def test_q3_http526_falls_back_to_official_cvm_pdf(monkeypatch):
    repo = IssuerRepository()
    requests = []

    async def fetch_pdf(url, *, fetcher=None):
        requests.append(url)
        if url == RELEASE_URL:
            raise RuntimeError("Bemobi IR HTTP 526; official MZiQ alternative unavailable")
        assert url == web.CVM_3Q26_RELEASE_URL
        return b"%PDF-1.4 official CVM", url, False

    monkeypatch.setattr(web, "_fetch_result_payload", fetch_pdf)
    monkeypatch.setattr(web, "_pdf_text", lambda _: Q3_TEXT)

    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-13",
    ))
    assert result["status"] == "ok"
    assert result["period"] == "3Q26"
    assert result["resolved_url"] == web.CVM_3Q26_RELEASE_URL
    assert requests == [RELEASE_URL, web.CVM_3Q26_RELEASE_URL]
    assert repo.documents[-1]["source_code"] == "CVM"
    assert repo.documents[-1]["metadata"]["resolution"] == "OFFICIAL_CVM_3Q26_FALLBACK"
    fact_writes = [
        params for sql, params in repo.writes
        if "INSERT INTO bemobi_investor_facts" in sql and params[0] == "RESULT"
    ]
    assert fact_writes
    assert "CVM" in [str(value) for value in fact_writes[0]]
    assert web.CVM_3Q26_RELEASE_URL in [
        str(value) for value in fact_writes[0]
    ]


def test_wrong_quarter_in_official_cvm_fallback_is_rejected(monkeypatch):
    repo = IssuerRepository()

    async def fetch_pdf(url, *, fetcher=None):
        if url == RELEASE_URL:
            raise RuntimeError("Bemobi IR HTTP 526")
        assert url == web.CVM_3Q26_RELEASE_URL
        return b"%PDF-1.4 official CVM", url, False

    monkeypatch.setattr(web, "_fetch_result_payload", fetch_pdf)
    monkeypatch.setattr(web, "_pdf_text", lambda _: Q3_TEXT.replace("3Q26", "2Q26"))

    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-13",
    ))
    assert result["status"] == "not_available"
    assert result["rows_written"] == 0
    assert any("forventet 3Q26" in str(error) for error in result["errors"])
    assert repo.writes == []


def test_cvm_fallback_is_disabled_for_unmatched_title_date_and_nonofficial_url():
    candidate = {
        "source_code": "BEMOBI_IR",
        "url": RELEASE_URL,
        "title": "Release 3T26 / 3Q26",
        "published_at": "2026-11-12T00:00:00Z",
    }
    assert web._official_cvm_q3_release_fallback(candidate) == web.CVM_3Q26_RELEASE_URL
    for invalid in (
        {**candidate, "title": "Earnings Presentation 3Q26"},
        {**candidate, "title": "Release 2T26 / 2Q26"},
        {**candidate, "published_at": "2026-11-11T00:00:00Z"},
        {**candidate, "source_code": "UNVERIFIED"},
        {**candidate, "url": "https://evil.example/release.pdf"},
    ):
        assert web._official_cvm_q3_release_fallback(invalid) is None


def test_q3_narrative_margin_follows_growth_without_confusing_the_two_percentages():
    text = Q3_TEXT.replace(
        "Adjusted EBITDA grew 38% YoY to R$86.8 million.",
        "Adjusted EBITDA recorded growth of 38% YoY, to R$86.8 million, "
        "with a 2.0 p.p. margin expansion to 35.4%.",
    ).replace("Adjusted EBITDA Margin 35.4%", "")
    result = web.parse_bemobi_result_text(text, published_date="2026-11-12")
    assert result["adjusted_ebitda_mbrl"] == 86.8
    assert result["adjusted_ebitda_margin_pct"] == 35.4


def test_q3_without_any_margin_does_not_invent_reported_margin():
    text = Q3_TEXT.replace("Adjusted EBITDA Margin 35.4%", "")
    result = web.parse_bemobi_result_text(text, published_date="2026-11-12")
    assert result["adjusted_ebitda_margin_pct"] is None


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


class ExistingQ3MarginRepository(IssuerRepository):
    def __init__(self, *, revenue=245.0, margin=None, cash=None):
        super().__init__()
        self.saved = json.dumps({
            "period": "3Q26",
            "adjusted_net_revenue_mbrl": revenue,
            "adjusted_ebitda_mbrl": 87.0,
            "adjusted_ebitda_margin_pct": margin,
            "cash_mbrl": cash,
            "adjusted_net_income_mbrl": 51.0,
        })

    async def first(self, sql, parameters=()):
        if "FROM bemobi_investor_facts" in sql and "fact_type='RESULT'" in sql:
            return {"id": 11, "payload_json": self.saved}
        return await super().first(sql, parameters)


def test_existing_q3_result_repairs_reported_margin_without_overwriting_amounts(monkeypatch):
    repo = ExistingQ3MarginRepository()

    async def fetch_pdf(url, *, fetcher=None):
        assert url == RELEASE_URL
        return b"%PDF-1.4 test", url, False

    monkeypatch.setattr(web, "_fetch_result_payload", fetch_pdf)
    monkeypatch.setattr(web, "_pdf_text", lambda _raw: Q3_TEXT)
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-18",
    ))
    assert result["status"] == "ok"
    assert result["reason"] == "official_result_margin_backfilled"
    assert result["rows_updated"] == 1
    updates = [(sql, params) for sql, params in repo.writes
               if "UPDATE bemobi_investor_facts" in sql]
    assert len(updates) == 1
    saved = json.loads(updates[0][1][0])
    assert saved["period"] == "3Q26"
    assert saved["adjusted_ebitda_margin_pct"] == 35.4
    assert saved["adjusted_net_revenue_mbrl"] == 245.0
    assert saved["adjusted_ebitda_mbrl"] == 87.0
    assert updates[0][1][1] == 11
    assert updates[0][1][2] == repo.saved


def test_existing_q3_margin_backfill_rejects_mismatched_official_amounts(monkeypatch):
    repo = ExistingQ3MarginRepository(revenue=200.0)

    async def fetch_pdf(url, *, fetcher=None):
        return b"%PDF-1.4 test", url, False

    monkeypatch.setattr(web, "_fetch_result_payload", fetch_pdf)
    monkeypatch.setattr(web, "_pdf_text", lambda _raw: Q3_TEXT)
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-18",
    ))
    assert result["status"] == "skipped"
    assert result["reason"] == "official_result_margin_backfill_unavailable"
    assert repo.writes == []


def test_existing_q3_margin_is_never_replaced_when_already_reported(monkeypatch):
    repo = ExistingQ3MarginRepository(margin=35.4)

    async def should_not_refetch(*args, **kwargs):
        raise AssertionError("Do not refetch known reported margin")

    monkeypatch.setattr(web, "_fetch_result_payload", should_not_refetch)
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-18",
    ))
    assert result["status"] == "skipped"
    assert result["reason"] == "latest_result_already_ingested"
    assert repo.writes == []


def test_existing_q3_bad_cash_is_repaired_from_same_official_document(monkeypatch):
    repo = ExistingQ3MarginRepository(margin=35.4, cash=2025.0)

    async def fetch_pdf(url, *, fetcher=None):
        assert url == RELEASE_URL
        return b"%PDF-1.4", url, False

    monkeypatch.setattr(web, "_fetch_result_payload", fetch_pdf)
    monkeypatch.setattr(web, "_pdf_text", lambda _: Q3_TEXT + (
        " Even so, our cash position remains solid "
        "(R$319 million at the end of 3Q26)."
    ))
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-18",
    ))
    assert result["reason"] == "official_result_cash_backfilled"
    assert result["status"] == "ok"
    assert result["fields_updated"] == ["cash"]
    writes = [(sql, params) for sql, params in repo.writes
              if "UPDATE bemobi_investor_facts" in sql]
    assert len(writes) == 1
    updated = json.loads(writes[0][1][0])
    assert updated["cash_mbrl"] == 319.0
    assert updated["cash_quality"] == "OFFICIAL_REPORTED"
    assert updated["adjusted_ebitda_mbrl"] == 87.0
    assert updated["adjusted_ebitda_margin_pct"] == 35.4
    assert updated["period"] == "3Q26"


def test_existing_q3_bad_cash_not_replaced_with_missing_cash(monkeypatch):
    repo = ExistingQ3MarginRepository(margin=35.4, cash=2025.0)

    async def fetch_pdf(url, *, fetcher=None):
        return b"%PDF-1.4", url, False

    monkeypatch.setattr(web, "_fetch_result_payload", fetch_pdf)
    monkeypatch.setattr(web, "_pdf_text", lambda _: Q3_TEXT)
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-18",
    ))
    assert result["status"] == "skipped"
    assert repo.writes == []


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



CVM_Q3_SOURCE_URL = (
    "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx"
    "?Tela=ext&descTipo=IPE&CodigoInstituicao=1"
    "&numProtocolo=1588745&numSequencia=1113451&numVersao=1"
)


def test_exact_cvm_q3_filing_can_use_verified_r2_but_presentations_cannot():
    eligible = {
        "source_code": "CVM",
        "url": CVM_Q3_SOURCE_URL,
        "title": "Dados Econômico-Financeiros — Release 3T26 / 3Q26",
        "published_at": "2026-11-12T00:00:00Z",
    }
    assert web._official_cvm_q3_release_fallback(eligible) == web.CVM_3Q26_RELEASE_URL
    invalid = (
        {**eligible, "url": CVM_Q3_SOURCE_URL.replace("1588745", "1589034")},
        {**eligible, "url": CVM_Q3_SOURCE_URL.replace("rad.cvm.gov.br", "evil.example")},
        {**eligible, "url": CVM_Q3_SOURCE_URL.replace("1113451", "1113740")},
        {**eligible, "title": "Comunicado ao Mercado — Apresentação de resultados 3T26 | 3Q26"},
        {**eligible, "published_at": "2026-11-13T00:00:00Z"},
    )
    for candidate in invalid:
        assert web._official_cvm_q3_release_fallback(candidate) is None
    assert not web._is_official_earnings_release_candidate(invalid[3])


class CvmQ3Repository(IssuerRepository):
    async def first(self, sql, parameters=()):
        if "FROM runtime_state" in sql:
            return None
        return await super().first(sql, parameters)

    async def all(self, sql, parameters=()):
        assert "FROM company_news" in sql
        return [
            {
                "id": 101, "source_code": "CVM",
                "title": "Comunicado ao Mercado — Apresentação de resultados 3T26 | 3Q26",
                "url": CVM_Q3_SOURCE_URL.replace("1588745", "1589034"),
                "published_at": "2026-11-13T00:00:00Z",
            },
            {
                "id": 102, "source_code": "CVM",
                "title": "Dados Econômico-Financeiros — Release 3T26 / 3Q26",
                "url": CVM_Q3_SOURCE_URL,
                "published_at": "2026-11-12T00:00:00Z",
            },
        ]


def test_production_cvm_526_uses_exact_verified_r2_and_excludes_presentation(monkeypatch):
    repo = CvmQ3Repository()

    class ArchiveBucket:
        async def put(self, key, payload):
            assert key and payload.startswith(b"%PDF")

    bucket = ArchiveBucket()
    requests = []

    async def tls_526(url, *, fetcher=None):
        requests.append(url)
        raise RuntimeError("Bemobi result release feilet med HTTP 526")

    async def verified_r2(found_bucket, kind):
        assert found_bucket is bucket and kind == "result"
        return b"%PDF-1.6 verified official Q3", web.CVM_3Q26_RELEASE_URL

    monkeypatch.setattr(web, "_fetch_result_payload", tls_526)
    monkeypatch.setattr(web, "read_verified_q3_document", verified_r2)
    monkeypatch.setattr(web, "_pdf_text", lambda _: Q3_TEXT)
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-21", archive_bucket=bucket,
    ))
    assert result["status"] == "ok"
    assert result["period"] == "3Q26"
    assert result["resolved_url"] == web.CVM_3Q26_RELEASE_URL
    assert requests == [CVM_Q3_SOURCE_URL, web.CVM_3Q26_RELEASE_URL]
    assert repo.documents[0]["source_code"] == "CVM"
    assert repo.documents[0]["url"] == web.CVM_3Q26_RELEASE_URL
    assert any("INSERT INTO bemobi_investor_facts" in sql for sql, _ in repo.writes)


class ExistingCvmQ3MarginRepository(ExistingQ3MarginRepository):
    async def first(self, sql, parameters=()):
        if "FROM runtime_state" in sql:
            return None
        return await super().first(sql, parameters)

    async def all(self, sql, parameters=()):
        return await CvmQ3Repository.all(self, sql, parameters)


def test_existing_cvm_q3_margin_repairs_via_verified_r2_after_http526(monkeypatch):
    repo = ExistingCvmQ3MarginRepository(cash=319.0)
    bucket = object()

    async def tls_526(url, *, fetcher=None):
        raise RuntimeError("HTTP 526")

    async def verified_r2(found_bucket, kind):
        assert found_bucket is bucket and kind == "result"
        return b"%PDF-1.6 verified official Q3", web.CVM_3Q26_RELEASE_URL

    monkeypatch.setattr(web, "_fetch_result_payload", tls_526)
    monkeypatch.setattr(web, "read_verified_q3_document", verified_r2)
    monkeypatch.setattr(web, "_pdf_text", lambda _: Q3_TEXT)
    result = asyncio.run(web.sync_latest_result_release(
        repo, target_date="2026-11-21", archive_bucket=bucket,
    ))
    assert result["status"] == "ok"
    assert result["reason"] == "official_result_margin_backfilled"
    updates = [(sql, p) for sql, p in repo.writes if "UPDATE bemobi_investor_facts" in sql]
    assert len(updates) == 1
    saved = json.loads(updates[0][1][0])
    assert saved["adjusted_ebitda_margin_pct"] == 35.4
    assert saved["cash_mbrl"] == 319.0
    assert saved["adjusted_net_revenue_mbrl"] == 245.0



def test_existing_cvm_q3_only_claims_pinned_sha_provenance_with_resolved_doc():
    class ProvenanceRepository(ExistingCvmQ3MarginRepository):
        def __init__(self, *, resolved=True):
            super().__init__(cash=319.0, margin=35.4)
            self.resolved = resolved

        async def first(self, sql, parameters=()):
            if "FROM source_documents" in sql:
                if "parent_source_document_id" in sql:
                    assert parameters == (
                        web.PINNED_Q3_DOCUMENTS["result"]["sha256"], 102,
                    )
                    return {"id": 8059, "url": web.Q3_RELEASE_URL} if self.resolved else None
                assert parameters == (102, web.PINNED_Q3_DOCUMENTS["result"]["sha256"])
                return None
            return await super().first(sql, parameters)

    good = asyncio.run(web.sync_latest_result_release(
        ProvenanceRepository(), target_date="2026-11-21",
    ))
    assert good["status"] == "skipped"
    assert good["reason"] == "latest_result_already_ingested"
    assert good["verified_existing_official_q3"] is True

    missing = asyncio.run(web.sync_latest_result_release(
        ProvenanceRepository(resolved=False), target_date="2026-11-21",
    ))
    assert missing["status"] == "skipped"
    assert missing["verified_existing_official_q3"] is False


def test_direct_cvm_q3_provenance_requires_exact_source_row_and_sha():
    class DirectRepository:
        def __init__(self, direct_url, digest, *, source_id=102):
            self.direct_url = direct_url
            self.digest = digest
            self.source_id = source_id
            self.calls = []

        async def first(self, sql, parameters=()):
            self.calls.append((sql, parameters))
            assert "s.code='CVM'" in sql
            if "parent_source_document_id" in sql:
                return None
            assert "sd.id=? AND sd.content_sha256=?" in sql
            if parameters == (self.source_id, self.digest):
                return {"id": self.source_id, "url": self.direct_url}
            return None

    digest = web.PINNED_Q3_DOCUMENTS["result"]["sha256"]
    candidate = {
        "id": 102,
        "source_code": "CVM",
        "title": "Dados Econômico-Financeiros | Press-release | Release 3T26",
        "url": web.Q3_RELEASE_URL,
        "published_at": "2026-11-12T00:00:00Z",
        "live_cvm": True,
        "mirror_artifact": {
            "url": web.Q3_RELEASE_URL, "period": "3Q26", "sha256": digest,
        },
    }
    existing = {"payload_json": json.dumps({"period": "3Q26"})}

    def verify(repo, selected=candidate, stored=existing):
        return asyncio.run(web._verified_existing_cvm_q3_result(repo, selected, stored))

    assert verify(DirectRepository(CVM_Q3_SOURCE_URL, digest))
    assert not verify(DirectRepository(CVM_Q3_SOURCE_URL, "0" * 64))
    assert not verify(DirectRepository(CVM_Q3_SOURCE_URL, digest, source_id=999))
    assert not verify(DirectRepository(CVM_Q3_SOURCE_URL.replace("1588745", "1589034"), digest))
    assert not verify(DirectRepository(CVM_Q3_SOURCE_URL, digest),
                      {**candidate, "mirror_artifact": {**candidate["mirror_artifact"], "sha256": "0" * 64}})
    assert not verify(DirectRepository(CVM_Q3_SOURCE_URL, digest),
                      stored={"payload_json": json.dumps({"period": "2Q26"})})
