from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

import brazil_investing_consensus as investing  # noqa: E402
from brazil_dashboard_v2 import _resolve_latest_high_macro  # noqa: E402


def test_latest_high_macro_uses_exact_high_importance_only() -> None:
    events = [
        {
            "date": "2026-12-02",
            "name": "BNP Q3",
            "kind": "gdp",
            "importance": "Middels–høy",
            "bemobi_impact": "BNP-relevans",
        },
        {
            "date": "2026-09-11",
            "name": "IPCA",
            "kind": "inflation",
            "importance": "Høy",
            "bemobi_impact": "Inflasjonsrelevans",
        },
    ]
    pages = {
        "gdp": (
            investing._EVENT_URLS["gdp"],
            [
                {
                    "date": "2026-09-03",
                    "time_utc": "12:00",
                    "actual": "1.2%",
                    "forecast": "1.0%",
                    "previous": "0.8%",
                }
            ],
        ),
        "ipca": (
            investing._EVENT_URLS["ipca"],
            [
                {
                    "date": "2026-09-01",
                    "time_utc": "12:00",
                    "actual": "0.30%",
                    "forecast": "0.35%",
                    "previous": "0.25%",
                }
            ],
        ),
    }

    latest = investing._latest_high_importance_release(
        events,
        pages,
        as_of_date="2026-09-04",
    )

    assert latest is not None
    assert latest["name"] == "IPCA"
    assert latest["importance"] == "Høy"
    assert latest["actual"] == "0.30%"
    assert latest["forecast"] == "0.35%"
    assert latest["surprise"] == -0.05


def test_investing_explains_missing_forecast_and_source_error(monkeypatch) -> None:
    async def no_forecast(url: str, *, fetcher=None) -> str:
        del fetcher
        assert "services-sector-growth" in url
        return (
            "<table><tr><td>Sep 10, 2026</td><td>12:00</td><td></td>"
            "<td></td><td>0.5%</td></tr></table>"
        )

    monkeypatch.setattr(investing, "_fetch_html", no_forecast)
    events = [
        {
            "date": "2026-09-10",
            "name": "Tjenesteaktivitet (PMS)",
            "kind": "services",
            "importance": "Middels–høy",
        }
    ]
    enriched, _ = asyncio.run(
        investing.enrich_calendar_from_investing(events, as_of_date="2026-09-04")
    )
    assert enriched[0]["investing_consensus_status"]["code"] == "NO_FORECAST_PUBLISHED"

    async def blocked(url: str, *, fetcher=None) -> str:
        del url, fetcher
        return "<html><body>Access denied</body></html>"

    monkeypatch.setattr(investing, "_fetch_html", blocked)
    enriched, _ = asyncio.run(
        investing.enrich_calendar_from_investing(events, as_of_date="2026-09-04")
    )
    assert enriched[0]["investing_consensus_status"]["code"] == "SOURCE_ERROR"


class _StateRepository:
    def __init__(self) -> None:
        self.value: str | None = None
        self.writes = 0

    async def first(self, sql: str, params: tuple[str, ...]):
        assert "runtime_state" in sql
        assert params == ("brazil.latest_high_macro.v1",)
        return {"value": self.value} if self.value is not None else None

    async def run(self, sql: str, params: tuple[str, ...]):
        assert "runtime_state" in sql
        assert params[0] == "brazil.latest_high_macro.v1"
        self.value = params[1]
        self.writes += 1


def test_latest_high_macro_persists_until_a_newer_high_release_arrives() -> None:
    repository = _StateRepository()
    first = {
        "date": "2026-09-01",
        "name": "IPCA",
        "importance": "Høy",
        "actual": "0.30%",
    }
    newer = {
        "date": "2026-09-11",
        "name": "IPCA",
        "importance": "Høy",
        "actual": "0.25%",
    }

    resolved = asyncio.run(
        _resolve_latest_high_macro(repository, first, as_of_date="2026-09-04")
    )
    assert resolved == first
    assert repository.writes == 1

    carried = asyncio.run(
        _resolve_latest_high_macro(repository, None, as_of_date="2026-09-10")
    )
    assert carried == first
    assert repository.writes == 1

    replaced = asyncio.run(
        _resolve_latest_high_macro(repository, newer, as_of_date="2026-09-11")
    )
    assert replaced == newer
    assert json.loads(repository.value or "{}")["date"] == "2026-09-11"
    assert repository.writes == 2


def test_brazil_frontend_shows_latest_release_and_specific_consensus_reasons() -> None:
    frontend = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "BrazilPage.tsx"
    ).read_text(encoding="utf-8")

    assert "SISTE VIKTIGE MAKROTALL" in frontend
    assert "FAKTISK" in frontend
    assert "FORVENTET" in frontend
    assert "BEMOBI-RELEVANS" in frontend
    assert "Forecast-feltet er tomt" in frontend
    assert "hentingen feilet eller ble blokkert" in frontend
    assert "ingen rad matcher den offisielle publiseringsdatoen" in frontend
