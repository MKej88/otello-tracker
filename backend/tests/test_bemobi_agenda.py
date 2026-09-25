from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cloudflare/src"))
from bemobi_agenda import (  # noqa: E402
    BOOTSTRAP_ROWS, STATE_KEY, agenda_events, merge_agenda_events, parse_agenda, refresh_agenda,
)
from news_events import news_and_events  # noqa: E402
from overview_events import overview_events  # noqa: E402


class Repository:
    def __init__(self): self.state = {}
    async def first(self, sql, params=()):
        if "runtime_state" in sql:
            value = self.state.get(params[0])
            return {"value": value} if value else None
        return None
    async def all(self, *args): return []
    async def run(self, sql, params): self.state[params[0]] = params[1]


def test_official_dates_are_november_and_noon_placeholder_is_not_a_time():
    events = parse_agenda(BOOTSTRAP_ROWS)
    assert [event["date"] for event in events] == ["2026-11-12", "2026-11-13"]
    assert [event["category"] for event in events] == ["RESULTS", "CONFERENCE_CALL"]
    assert all(event["starts_at_utc"] is None for event in events)
    assert all(event["time_status"] == "NOT_PUBLISHED" for event in events)


@pytest.mark.parametrize("dates,timezone,expected_date,expected_utc", [
    ("20261113T110000/20261113T120000", "America/Sao_Paulo", "2026-11-13", "2026-11-13T14:00:00Z"),
    ("20260813T110000/20260813T120000", "America/Sao_Paulo", "2026-08-13", "2026-08-13T14:00:00Z"),
    ("20261113T233000Z/20261114T003000Z", "", "2026-11-14", "2026-11-13T23:30:00Z"),
    ("20260813T223000Z/20260813T233000Z", "", "2026-08-14", "2026-08-13T22:30:00Z"),
])
def test_timed_exports_handle_dst_and_midnight(dates, timezone, expected_date, expected_utc):
    row = {**BOOTSTRAP_ROWS[1], "google_cal_url": f"https://www.google.com/calendar/render?dates={dates}&ctz={timezone}"}
    event = parse_agenda([row])[0]
    assert event["date"] == expected_date
    assert event["starts_at_utc"] == expected_utc


def test_unqualified_time_is_not_guessed():
    row = {**BOOTSTRAP_ROWS[1], "google_cal_url": "https://www.google.com/calendar/render?dates=20261113T110000/20261113T120000"}
    assert parse_agenda([row])[0]["starts_at_utc"] is None


@pytest.mark.parametrize("payload", [{"error": "unavailable"}, [None], [{"event_id": "a"}], BOOTSTRAP_ROWS * 2])
def test_invalid_or_duplicate_feed_is_rejected(payload):
    with pytest.raises((ValueError, TypeError)):
        parse_agenda(payload)


def test_bootstrap_is_not_visible_before_observation():
    assert asyncio.run(agenda_events(Repository(), as_of_date="2026-09-24")) == []


def test_agenda_cache_read_failure_is_not_hidden_by_bootstrap():
    class FailingRepository(Repository):
        async def first(self, sql, params=()):
            raise RuntimeError("D1 unavailable")

    with pytest.raises(RuntimeError, match="D1 unavailable"):
        asyncio.run(agenda_events(FailingRepository(), as_of_date="2026-09-25"))


def test_refresh_replaces_rescheduled_events_and_can_clear_cancelled_events():
    repo = Repository()
    class Response:
        ok = True
        async def text(self): return json.dumps(payload)
    async def fetcher(*args, **kwargs): return Response()
    payload = [{**BOOTSTRAP_ROWS[0], "event_date": "2026-11-16T12:00:00.000Z", "google_cal_url": ""}]
    status = asyncio.run(refresh_agenda(repo, target_date="2026-09-25", fetcher=fetcher))
    assert status["status"] == "ok"
    events = asyncio.run(agenda_events(repo, as_of_date="2026-09-25"))
    assert len(events) == 1 and events[0]["date"] == "2026-11-16"
    payload = []
    asyncio.run(refresh_agenda(repo, target_date="2026-09-25", fetcher=fetcher))
    assert asyncio.run(agenda_events(repo, as_of_date="2026-09-25")) == []


def test_failed_refresh_preserves_last_good():
    repo = Repository()
    repo.state[STATE_KEY] = json.dumps({"events": parse_agenda(BOOTSTRAP_ROWS), "observed_date": "2026-09-25"})
    previous = repo.state[STATE_KEY]
    async def fail(*args, **kwargs): raise RuntimeError("upstream unavailable")
    status = asyncio.run(refresh_agenda(repo, target_date="2026-09-26", fetcher=fail))
    assert status["last_good_preserved"]
    assert repo.state[STATE_KEY] == previous


def test_official_agenda_replaces_legacy_report_but_keeps_other_events():
    legacy = [{"id": "bemobi-report-2026Q3", "date": "2026-11-10"}, {"id": "other", "date": "2026-10-01"}]
    merged = merge_agenda_events(legacy, parse_agenda(BOOTSTRAP_ROWS))
    assert len(merged) == 3
    assert merged[0]["id"] == "other"
    assert not any(x["date"] == "2026-11-10" for x in merged)


@pytest.mark.parametrize("loader", [news_and_events, overview_events])
def test_both_api_feeds_expose_official_events_and_remove_past_dates(loader):
    result = asyncio.run(loader(Repository(), as_of_date="2026-11-13"))
    assert len(result["events"]) == 1
    assert result["events"][0]["category"] == "CONFERENCE_CALL"
    assert result["events"][0]["starts_at_utc"] is None
