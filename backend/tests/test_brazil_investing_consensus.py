from __future__ import annotations

import asyncio
import sys
from pathlib import Path

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

import brazil_investing_consensus as investing  # noqa: E402


def _page(*rows: str) -> str:
    return "<html><body><table>" + "".join(rows) + "</table></body></html>"


def _row(date: str, time: str, actual: str, forecast: str, previous: str) -> str:
    values = [date, time, actual, forecast, previous]
    return "<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>"


def test_parser_reads_investing_forecast_previous_and_utc_time() -> None:
    rows = investing._parse_rows(
        _page(
            _row("Sep 01, 2026 (Q2)", "12:00", "", "0.4%", "1.1%"),
            _row("May 29, 2026 (Q1)", "12:00", "1.1%", "1.0%", "0.3%"),
        )
    )

    assert rows[0] == {
        "date": "2026-09-01",
        "time_utc": "12:00",
        "actual": None,
        "forecast": "0.4%",
        "previous": "1.1%",
    }


def test_investing_overrides_focus_when_event_forecast_exists(monkeypatch) -> None:
    async def fake_fetch_html(url: str, *, fetcher=None) -> str:
        assert "brazil-gdp-858" in url
        return _page(_row("Sep 01, 2026 (Q2)", "12:00", "", "0.4%", "1.1%"))

    monkeypatch.setattr(investing, "_fetch_html", fake_fetch_html)
    events = [
        {
            "date": "2026-09-01",
            "name": "BNP Q2",
            "kind": "gdp",
            "reference": "2026 Q2",
            "expectation": {
                "label": "Focus BNP Q2 2026",
                "value": 0.2,
                "unit": "%",
                "survey_date": "2026-08-28",
                "event_consensus": True,
                "provider": "BCB Focus",
            },
        }
    ]

    enriched, status = asyncio.run(
        investing.enrich_calendar_from_investing(events, as_of_date="2026-09-01")
    )

    expectation = enriched[0]["expectation"]
    assert expectation["provider"] == "Investing.com"
    assert expectation["value"] == 0.4
    assert expectation["previous"] == "1.1%"
    assert expectation["release_at_utc"] == "2026-09-01T12:00:00Z"
    assert enriched[0]["investing_consensus_status"]["code"] == "AVAILABLE"
    assert status["consensus_events"] == 1
    assert status["timed_events"] == 1


def test_release_time_is_kept_when_forecast_is_not_published(monkeypatch) -> None:
    async def fake_fetch_html(url: str, *, fetcher=None) -> str:
        assert "industrial" not in url
        return _page(_row("Sep 15, 2026 (Jul)", "12:00", "", "", "0.5%"))

    monkeypatch.setattr(investing, "_fetch_html", fake_fetch_html)
    events = [
        {
            "date": "2026-09-15",
            "name": "Detaljhandel (PMC)",
            "kind": "retail",
            "reference": "jul. 2026",
        }
    ]

    enriched, status = asyncio.run(
        investing.enrich_calendar_from_investing(events, as_of_date="2026-09-01")
    )

    expectation = enriched[0]["expectation"]
    assert expectation["event_consensus"] is False
    assert expectation["release_at_utc"] == "2026-09-15T12:00:00Z"
    assert "value" not in expectation
    assert (
        enriched[0]["investing_consensus_status"]["code"]
        == "NO_FORECAST_PUBLISHED"
    )
    assert status["consensus_events"] == 0
    assert status["timed_events"] == 1


def test_valid_page_without_matching_date_is_reported_separately(monkeypatch) -> None:
    async def fake_fetch_html(url: str, *, fetcher=None) -> str:
        assert "services-sector-growth" in url
        return _page(_row("Aug 14, 2026", "12:00", "0.3%", "0.2%", "0.1%"))

    monkeypatch.setattr(investing, "_fetch_html", fake_fetch_html)
    events = [
        {
            "date": "2026-09-10",
            "name": "Tjenesteaktivitet (PMS)",
            "kind": "services",
            "reference": "jul. 2026",
        }
    ]

    enriched, status = asyncio.run(
        investing.enrich_calendar_from_investing(events, as_of_date="2026-09-01")
    )

    assert enriched[0]["investing_consensus_status"]["code"] == "NO_MATCH"
    assert status["pages_ready"] == 1
    assert status["matched_events"] == 0


def test_empty_success_response_is_reported_as_source_error(monkeypatch) -> None:
    async def fake_fetch_html(url: str, *, fetcher=None) -> str:
        return "<html><body>Access denied</body></html>"

    monkeypatch.setattr(investing, "_fetch_html", fake_fetch_html)
    events = [
        {
            "date": "2026-09-01",
            "name": "BNP Q2",
            "kind": "gdp",
            "reference": "2026 Q2",
        }
    ]

    enriched, status = asyncio.run(
        investing.enrich_calendar_from_investing(
            events,
            as_of_date="2026-09-01",
        )
    )

    assert enriched[0]["date"] == events[0]["date"]
    assert enriched[0]["investing_consensus_status"]["code"] == "SOURCE_ERROR"
    assert status["ready"] is False
    assert status["pages_ready"] == 0
    assert "ValueError" in status["errors"]["gdp"]


def test_copom_release_time_is_read_as_utc(monkeypatch) -> None:
    async def fake_fetch_html(url: str, *, fetcher=None) -> str:
        assert "interest-rate-decision-415" in url
        return _page(_row("Sep 16, 2026", "21:30", "", "14.00%", "14.00%"))

    monkeypatch.setattr(investing, "_fetch_html", fake_fetch_html)
    events = [{"date": "2026-09-16", "name": "Copom rentebeslutning", "kind": "copom"}]

    enriched, _ = asyncio.run(
        investing.enrich_calendar_from_investing(events, as_of_date="2026-09-01")
    )

    assert enriched[0]["expectation"]["release_at_utc"] == "2026-09-16T21:30:00Z"
