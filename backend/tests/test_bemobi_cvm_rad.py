"""Offline coverage of public RAD parsing and fail-closed source discovery."""
import asyncio
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
