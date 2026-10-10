from __future__ import annotations

import asyncio
import json

from src.overview_events import overview_events
from src.bemobi_agenda import BOOTSTRAP_ROWS, parse_agenda


class FakeRepository:
    def __init__(self, cached_expectations: dict | None = None) -> None:
        self.cached_expectations = cached_expectations
        self.queries: list[str] = []

    async def all(self, sql: str, params=()):
        self.queries.append(sql)
        return []

    async def first(self, sql: str, params=()):
        self.queries.append(sql)
        if "bemobi_investor_facts" in sql:
            return None
        if "runtime_state" in sql and self.cached_expectations is not None:
            return {
                "value": json.dumps(
                    {"expectations": self.cached_expectations},
                    ensure_ascii=False,
                ),
                "updated_at": "2026-09-06T12:00:00Z",
            }
        return None


def test_overview_events_returns_calendar_without_live_external_calls() -> None:
    repository = FakeRepository()

    result = asyncio.run(overview_events(repository, as_of_date="2026-09-06"))

    assert result["ready"] is True
    assert result["meta"]["live_external_fetches"] is False
    assert result["events"] == []
    assert result["calendar"][0]["date"] == "2026-09-10"
    assert any(
        event["date"] == "2026-09-11" and event["name"] == "IPCA"
        for event in result["calendar"]
    )
    assert all("company_news" not in query for query in repository.queries)


def test_overview_events_restores_last_good_macro_time_and_consensus() -> None:
    key = "2026-09-11|IPCA|aug. 2026"
    repository = FakeRepository(
        {
            key: {
                "value": 0.32,
                "unit": "%",
                "event_consensus": True,
                "previous": "0,24 %",
                "release_at_utc": "2026-09-11T12:00:00Z",
                "survey_date": "2026-09-06",
            }
        }
    )

    result = asyncio.run(overview_events(repository, as_of_date="2026-09-06"))
    ipca = next(
        event
        for event in result["calendar"]
        if event["date"] == "2026-09-11" and event["name"] == "IPCA"
    )

    assert result["meta"]["cached_macro_expectations_restored"] == 1
    assert ipca["expectation"]["event_consensus"] is True
    assert ipca["expectation"]["release_at_utc"] == "2026-09-11T12:00:00Z"
    assert ipca["expectation"]["fallback_cached"] is True


def test_official_report_event_gets_same_quarter_estimates_after_reschedule(monkeypatch):
    from src import overview_events as module

    estimates = [
        {"broker": "BTG Pactual", "metric": "revenue_mbrl", "value_mbrl": 239.8},
        {"broker": "BTG Pactual", "metric": "adjusted_ebitda_mbrl", "value_mbrl": 85.5},
    ]

    class Repository(FakeRepository):
        async def first(self, sql, params=()):
            if "bemobi_investor_facts" in sql:
                self.queries.append(sql)
                return {"fact_key": "3Q26", "payload_json": json.dumps({
                    "period": "3Q26", "status": "PUBLIC_ESTIMATES_AVAILABLE", "estimates": estimates,
                })}
            return await super().first(sql, params)

    official = parse_agenda([
        {**BOOTSTRAP_ROWS[0], "event_date": "2026-11-16T12:00:00.000Z", "google_cal_url": ""},
        BOOTSTRAP_ROWS[1],
        {**BOOTSTRAP_ROWS[0], "event_id": "other-quarter", "event_name": "Earning Release - 4Q26"},
    ])

    async def agenda(_repository, *, as_of_date):
        return official

    monkeypatch.setattr(module, "agenda_events", agenda)
    repository = Repository()
    result = asyncio.run(overview_events(repository, as_of_date="2026-10-10"))
    preview_event = next(e for e in result["events"] if e.get("quarter_preview"))
    assert preview_event["date"] == "2026-11-16"
    assert preview_event["period"] == "2026Q3"
    assert preview_event["quarter_preview"] == {
        "period": "3Q26", "status": "PUBLIC_ESTIMATES_AVAILABLE", "estimates": estimates,
    }
    assert len([e for e in result["events"] if e.get("quarter_preview")]) == 1
    assert result["meta"]["live_external_fetches"] is False
    assert sum("bemobi_investor_facts" in query for query in repository.queries) == 1


def test_no_forecasts_for_official_report_when_source_is_missing():
    result = asyncio.run(overview_events(FakeRepository(), as_of_date="2026-10-10"))
    report = next(e for e in result["events"] if e["category"] == "RESULTS")
    assert report["date"] == "2026-11-12"
    assert "quarter_preview" not in report
