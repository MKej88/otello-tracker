from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cloudflare" / "src"))
import brazil_focus_report as report  # noqa: E402
from brazil_dashboard import _load_focus  # noqa: E402
from brazil_focus_resilience import resolve_annual_focus  # noqa: E402
from test_brazil_focus_resilience import FakeRepository  # noqa: E402

# Extracted annual rows, BCB R20260918.pdf, aggregate Hoje versus 5-day medians.
TEXT = """Focus Relatório de Mercado
Expectativas de Mercado 18 de setembro de 2026
2026 2027 2028 2029
Mediana - Agregado Há 4 Há 1 Hoje Resp. 5 dias Há 4 Há 1 Hoje Resp. 5 dias Há 4 Há 1 Hoje Resp. Há 4 Há 1 Hoje Resp.
IPCA (variação %) 5,02 4,90 4,92 (1) 146 4,97 91 4,25 4,30 4,30 (1) 146 4,35 91 3,80 3,80 3,80 (8) 118 3,50 3,50 3,50 (55) 111
PIB Total (variação % sobre ano anterior) 1,95 1,89 1,88 (2) 111 1,85 45 1,50 1,45 1,43 (2) 110 1,36 45 1,98 1,87 1,87 (1) 83 2,00 2,00 2,00 (79) 77
Câmbio (R$/US$) 5,20 5,20 5,20 (14) 115 5,16 58 5,30 5,28 5,28 (1) 115 5,27 58 5,30 5,30 5,30 (9) 86 5,36 5,36 5,36 (1) 81
Selic (% a.a) 13,75 13,75 13,50 (1) 140 13,50 77 12,00 12,00 12,00 (14) 139 12,00 76 10,50 10,50 10,50 (12) 116 10,00 10,00 10,00 (20) 109
"""


def parsed():
    return report.parse_report_text(TEXT, reference_date="2026-09-18", as_of_date="2026-09-25")


def test_published_report_reads_correct_sample_and_year_columns():
    result = parsed()
    assert result["values"]["ipca"]["2026"]["median"] == 4.92
    assert result["values"]["gdp"]["2027"]["median"] == 1.43
    assert result["values"]["selic"]["2026"]["median"] == 13.5
    assert result["values"]["usd_brl"]["2027"]["median"] == 5.28
    assert result["publication_date"] == "2026-09-21"


@pytest.mark.parametrize("text,reference,as_of", [
    (TEXT, "2026-09-17", "2026-09-25"),
    (TEXT, "2026-09-18", "2026-09-20"),
    (TEXT.replace("2026 2027 2028 2029", "2027 2028 2029 2030"), "2026-09-18", "2026-09-25"),
    (TEXT.replace("4,92", "-"), "2026-09-18", "2026-09-25"),
    (TEXT.replace("Hoje", "Changed"), "2026-09-18", "2026-09-25"),
])
def test_report_rejects_wrong_date_years_missing_values_and_changed_layout(text, reference, as_of):
    with pytest.raises(ValueError):
        report.parse_report_text(text, reference_date=reference, as_of_date=as_of)


def test_report_candidates_respect_publication_and_holiday():
    assert report.report_candidates("2026-09-20")[0].isoformat() == "2026-09-11"
    assert [x.isoformat() for x in report.report_candidates("2026-09-21")[:2]] == ["2026-09-18", "2026-09-17"]


def test_pdf_fallback_is_persisted_and_never_overwrites_newer_points(monkeypatch):
    async def load(*args, **kwargs): return parsed()
    monkeypatch.setattr(report, "load_published_focus", load)
    repo = FakeRepository()
    live = {"ready": True, "values": {"ipca": {"2026": {"median": 4.8, "survey_date": "2026-09-24"}}}}
    supplemented = asyncio.run(report.supplement_focus(repo, live, as_of_date="2026-09-25"))
    focus, status = asyncio.run(resolve_annual_focus(repo, supplemented, as_of_date="2026-09-25"))
    assert focus["values"]["ipca"]["2026"]["median"] == 4.8
    assert focus["values"]["gdp"]["2026"]["median"] == 1.88
    assert status["fallback_source"] == "BCB_PUBLISHED_FOCUS_REPORT"
    assert focus["focus_meta"]["mixed_dates"] is True
    old = parsed()
    result, _ = asyncio.run(resolve_annual_focus(repo, old, as_of_date="2026-09-25"))
    assert result["values"]["ipca"]["2026"]["median"] == 4.8


def test_report_failure_preserves_live_and_cache_path(monkeypatch):
    async def fail(*args, **kwargs): raise RuntimeError("network failure")
    monkeypatch.setattr(report, "load_published_focus", fail)
    live = {"ready": True, "values": {"selic": {"2026": {"median": 13.5, "survey_date": "2026-09-24"}}}}
    result = asyncio.run(report.supplement_focus(FakeRepository(), live, as_of_date="2026-09-25"))
    assert result["values"] == live["values"]
    assert "network failure" in result["report_errors"][0]


def test_report_download_is_cached(monkeypatch):
    repo = FakeRepository()
    calls = []
    class Response:
        ok = True
        status = 200
        async def arrayBuffer(self): return b"%PDF-fixture"
    async def fetcher(url, **kwargs):
        calls.append(url)
        return Response()
    monkeypatch.setattr(report, "parse_report_pdf", lambda *args, **kwargs: parsed())
    for _ in range(2):
        result = asyncio.run(report.load_published_focus(repo, as_of_date="2026-09-25", fetcher=fetcher))
        assert result["ready"]
    assert len(calls) == 1


def test_non_pdf_response_is_rejected():
    with pytest.raises(ValueError, match="ikke med PDF"):
        report.parse_report_pdf(b"<html>Access denied</html>", reference_date="2026-09-18", as_of_date="2026-09-25")


def test_healthy_api_does_not_download_report(monkeypatch):
    async def fail(*args, **kwargs): raise AssertionError("must not fetch")
    monkeypatch.setattr(report, "load_published_focus", fail)
    live = parsed()
    live["fallback"] = False
    result = asyncio.run(report.supplement_focus(FakeRepository(), live, as_of_date="2026-09-25"))
    assert "report_errors" not in result
    assert result["fallback"] is False


def test_missing_reports_are_bounded_and_failure_is_cached():
    calls = []
    repo = FakeRepository()
    class Response:
        ok = False
        status = 404
    async def fetcher(url, **kwargs):
        calls.append(url)
        return Response()
    for _ in range(2):
        result = asyncio.run(report.load_published_focus(repo, as_of_date="2026-09-25", fetcher=fetcher))
        assert not result["ready"]
    assert len(calls) == 6


def test_partial_api_failure_keeps_other_indicators_and_encodes_spaces():
    class Response:
        ok = True
        status = 200
        def __init__(self, label): self.label = label
        async def text(self):
            return json.dumps({"value": [{"Indicador": self.label, "Data": "2026-09-24", "DataReferencia": str(year), "Mediana": 4.5} for year in (2026, 2027)]})
    async def fetcher(url, **kwargs):
        assert "+" not in url
        assert "%20" in url
        label = parse_qs(urlparse(url).query)["$filter"][0].split("'")[1]
        if label == "Selic": raise RuntimeError("one source failed")
        return Response(label)
    result = asyncio.run(_load_focus("2026-09-25", fetcher=fetcher))
    assert set(result["values"]) == {"ipca", "gdp", "usd_brl"}
    assert "Selic" in result["indicator_errors"]
