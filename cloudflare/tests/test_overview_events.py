from __future__ import annotations

import asyncio
import json

from src.overview_events import overview_events


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
