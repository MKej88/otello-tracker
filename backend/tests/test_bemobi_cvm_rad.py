"""Offline coverage of public RAD parsing and fail-closed source discovery."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cloudflare" / "src"))
from datetime import date
from bemobi_cvm_rad import parse_rows, release_candidates, discover_live_releases, filing_identity

def line(title, category="Dados Econômico-Financeiros", kind="Press-release", status="Ativo",
         issuer="BEMOBI MOBILE TECH S.A.", protocol="123", version="1"):
    fields = [issuer, "025500", category, kind, title, "30/09/2026", "12/11/2026",
              status, "", "EN", f"OpenDownloadDocumentos('456','{version}','{protocol}','IPE')", title]
    return "$&".join(fields)

def payload(*lines):
    return {"d": {"temErro": False, "dados": "&*".join(lines)}}

def test_release_distinct_from_presentation_and_itr():
    rows = parse_rows(payload(line("Release 3T26 / 3Q26"),
        line("Apresentação de resultados 3T26", kind="Apresentações", protocol="124"),
        line("Informações Trimestrais (ITR)", kind="ITR", protocol="125"),
        line("Release 3T26", status="Cancelado", protocol="126")),
        date(2026,11,12), date(2026,11,13))
    result = release_candidates(rows)
    assert len(result) == 1
    assert result[0]["expected_period"] == "3Q26"
    assert filing_identity(result[0]["url"]) == ("123", "456", "1")
    assert "/ENETCONSULTA/" in result[0]["url"]

def test_revised_version_wins():
    rows = parse_rows(payload(line("Release 3T26", version="1"),
        line("Release 3T26", version="2")), date(2026,11,12), date(2026,11,13))
    assert release_candidates(rows)[0]["version"] == "2"

def test_public_endpoint_failure_is_explicit():
    class Response:
        ok = False
        status = 503
    async def fetch(*args, **kwargs):
        return Response()
    rows, status = asyncio.run(discover_live_releases(target_date="2026-11-24", fetcher=fetch))
    assert rows == []
    assert status["status"] == "not_available"
    assert "503" in status["error"]

def test_verified_live_period_reuses_stored_fact(monkeypatch):
    import json
    import bemobi_web_refresh as web
    rows = release_candidates(parse_rows(payload(line("Release 3T26")),
        date(2026,11,12), date(2026,11,13)))
    async def discover(**kwargs):
        return rows, {"status": "ok", "latest_period": "3Q26"}
    monkeypatch.setattr(web, "discover_live_releases", discover)
    class Repo:
        async def first(self, sql, parameters=()):
            if "FROM runtime_state" in sql:
                return None
            if "FROM source_documents sd" in sql:
                return {"id": 42, "source_code": "CVM", "url": rows[0]["url"],
                        "content_sha256": "a" * 64}
            if "fact_type='RESULT'" in sql:
                assert parameters == (42,)
                return {"id": 9, "payload_json": json.dumps({"period": "3Q26",
                    "cash_mbrl": 319, "adjusted_ebitda_margin_pct": 35.4})}
            raise AssertionError(sql)
        async def all(self, sql, parameters=()):
            return []
    result = asyncio.run(web.sync_latest_result_release(Repo(),
        target_date="2026-11-24", live_cvm=True))
    assert result["status"] == "skipped"
    assert result["report_coverage"] == "verified"
    assert result["cvm_live_discovery"]["latest_period"] == "3Q26"

def test_live_discovery_failure_preserves_existing_ingestion(monkeypatch):
    import bemobi_web_refresh as web
    async def discover(**kwargs):
        return [], {"status": "not_available", "error": "HTTP 526"}
    async def fallback(repository, **kwargs):
        assert kwargs["live_rows"] == []
        return {"status": "ok", "period": "3Q26", "rows_written": 3}
    monkeypatch.setattr(web, "discover_live_releases", discover)
    monkeypatch.setattr(web, "_sync_latest_result_release", fallback)
    result = asyncio.run(web.sync_latest_result_release(object(),
        target_date="2026-11-24", live_cvm=True))
    assert result["status"] == "ok"
    assert result["report_coverage"] == "unconfirmed"
    assert result["cvm_live_discovery"]["status"] == "not_available"


def test_future_quarter_requires_exact_current_filing_and_digest():
    import bemobi_web_refresh as web
    rows = release_candidates(parse_rows(payload(line("Release 3T26", version="2")),
        date(2026,11,12), date(2026,11,13)))
    candidate = {"id": 42, "source_code": "CVM", "live_cvm": True,
                 "url": rows[0]["url"], "expected_period": "4Q26",
                 "mirror_artifact": {"url": rows[0]["url"], "period": "4Q26", "sha256": "b" * 64}}
    class Repo:
        def __init__(self, row):
            self.row = row
        async def first(self, sql, parameters=()):
            assert parameters == (42,)
            return self.row
    valid = {"id": 42, "url": rows[0]["url"], "content_sha256": "b" * 64}
    assert asyncio.run(web._verified_current_cvm_filing(Repo(valid), candidate, "4Q26"))
    for row in (None, {**valid, "content_sha256": "c" * 64},
                {**valid, "content_sha256": None}, {**valid, "url": "https://example.com"}):
        assert not asyncio.run(web._verified_current_cvm_filing(Repo(row), candidate, "4Q26"))
    assert not asyncio.run(web._verified_current_cvm_filing(Repo(valid), candidate, "3Q26"))
