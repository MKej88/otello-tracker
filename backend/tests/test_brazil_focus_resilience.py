from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from brazil_focus_resilience import (  # noqa: E402
    BOOTSTRAP_REFERENCE_DATE,
    BOOTSTRAP_PUBLICATION_DATE,
    apply_cached_event_expectations,
    persist_event_expectations,
    resolve_annual_focus,
)
import brazil_dashboard_v2  # noqa: E402


class FakeRepository:
    def __init__(self) -> None:
        self.state: dict[str, dict[str, str]] = {}

    async def first(self, sql: str, params=()):
        if "runtime_state" not in sql:
            return None
        key = str(params[0])
        row = self.state.get(key)
        return dict(row) if row else None

    async def run(self, sql: str, params=()):
        if "runtime_state" in sql:
            key, value, updated_at = params
            self.state[str(key)] = {"value": str(value), "updated_at": str(updated_at)}
        return {"success": True}


def _live_focus(survey_date: str = "2026-08-28") -> dict:
    return {
        "ready": True,
        "values": {
            "selic": {
                "2026": {"median": 13.5, "survey_date": survey_date},
                "2027": {"median": 11.75, "survey_date": survey_date},
            },
            "ipca": {
                "2026": {"median": 4.95, "survey_date": survey_date},
                "2027": {"median": 4.20, "survey_date": survey_date},
            },
        },
        "source": "Banco Central do Brasil / Focus",
        "source_url": "https://example.test/focus",
    }


def test_published_focus_bootstrap_prevents_blank_table_on_first_olinda_failure() -> None:
    repo = FakeRepository()
    empty = {"ready": False, "values": {}, "note": "Olinda down"}

    focus, status = asyncio.run(
        resolve_annual_focus(repo, empty, as_of_date="2026-08-29")
    )

    assert focus["ready"] is True
    assert focus["data_source"] == "PUBLISHED_FOCUS_BOOTSTRAP"
    assert focus["values"]["selic"]["2026"]["median"] == 13.75
    assert focus["values"]["ipca"]["2027"]["median"] == 4.25
    assert focus["values"]["gdp"]["2026"]["median"] == 1.95
    assert focus["values"]["usd_brl"]["2027"]["median"] == 5.30
    assert status["fallback_source"] == "PUBLISHED_FOCUS_BOOTSTRAP"
    assert status["survey_date"] == BOOTSTRAP_REFERENCE_DATE


def test_last_good_focus_cache_beats_static_bootstrap_after_live_success() -> None:
    repo = FakeRepository()
    live = _live_focus()

    first, first_status = asyncio.run(
        resolve_annual_focus(repo, live, as_of_date="2026-08-29")
    )
    assert first["data_source"] == "BCB_OLINDA_LIVE"
    assert first_status["fallback"] is False

    empty = {"ready": False, "values": {}}
    fallback, status = asyncio.run(
        resolve_annual_focus(repo, empty, as_of_date="2026-08-30")
    )

    assert fallback["data_source"] == "LAST_GOOD_D1_CACHE"
    assert fallback["values"]["selic"]["2026"]["median"] == 13.5
    assert status["fallback_source"] == "LAST_GOOD_D1_CACHE"
    assert status["survey_date"] == "2026-08-28"


def test_partial_live_focus_merges_into_complete_cached_snapshot() -> None:
    repo = FakeRepository()
    asyncio.run(resolve_annual_focus(repo, _live_focus("2026-08-28"), as_of_date="2026-08-29"))
    partial = {
        "ready": True,
        "values": {"selic": {"2026": {"median": 13.25, "survey_date": "2026-08-29"}}},
    }

    asyncio.run(resolve_annual_focus(repo, partial, as_of_date="2026-08-29"))
    fallback, _ = asyncio.run(
        resolve_annual_focus(repo, {"ready": False, "values": {}}, as_of_date="2026-08-30")
    )

    assert fallback["values"]["selic"]["2026"]["median"] == 13.25
    assert fallback["values"]["selic"]["2027"]["median"] == 11.75
    assert fallback["values"]["ipca"]["2026"]["median"] == 4.95


@pytest.mark.parametrize("as_of_date", ["2026-08-20", "2026-08-21", "2026-08-22", "2026-08-23"])
def test_bootstrap_is_not_leaked_into_historical_dates_before_publication(
    as_of_date: str,
) -> None:
    repo = FakeRepository()
    empty = {"ready": False, "values": {}}

    focus, status = asyncio.run(
        resolve_annual_focus(repo, empty, as_of_date=as_of_date)
    )

    assert focus["ready"] is False
    assert focus["values"] == {}
    assert status["ready"] is False


def test_bootstrap_is_available_on_publication_date() -> None:
    repo = FakeRepository()
    empty = {"ready": False, "values": {}}

    focus, status = asyncio.run(
        resolve_annual_focus(repo, empty, as_of_date=BOOTSTRAP_PUBLICATION_DATE)
    )

    assert focus["data_source"] == "PUBLISHED_FOCUS_BOOTSTRAP"
    assert status["ready"] is True


def test_event_expectation_survives_later_olinda_failure() -> None:
    repo = FakeRepository()
    event = {
        "date": "2026-09-11",
        "name": "IPCA",
        "reference": "aug. 2026",
        "kind": "inflation",
        "expectation": {
            "label": "Focus IPCA 08/26",
            "value": 0.31,
            "unit": "%",
            "survey_date": "2026-08-28",
            "respondents": 95,
            "event_consensus": True,
            "provider": "BCB Focus",
        },
    }
    asyncio.run(persist_event_expectations(repo, [event]))

    without_live = {key: value for key, value in event.items() if key != "expectation"}
    restored, count = asyncio.run(
        apply_cached_event_expectations(
            repo,
            [without_live],
            as_of_date="2026-08-29",
        )
    )

    assert count == 1
    assert restored[0]["expectation"]["value"] == 0.31
    assert restored[0]["expectation"]["fallback_cached"] is True


def test_live_event_consensus_survives_cache_write_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    event = {
        "date": "2026-09-11",
        "name": "IPCA",
        "reference": "aug. 2026",
        "kind": "inflation",
    }
    expectation = {"event_consensus": True, "value": 0.31, "provider": "BCB Focus"}

    async def base_dashboard(*_args, **_kwargs):
        return {
            "as_of_date": "2026-08-29",
            "focus": {"ready": False, "values": {}},
            "calendar": [event],
            "source_status": {"focus": {"ready": False}},
        }

    async def enrich(rows, **_kwargs):
        enriched = [dict(rows[0], expectation=expectation)]
        return enriched, {"ready": True, "specific_expectations": 1}

    async def fail_persistence(*_args, **_kwargs):
        raise RuntimeError("D1 unavailable")

    async def no_cached(_repository, events, **_kwargs):
        return events, 0

    monkeypatch.setattr(brazil_dashboard_v2.base, "brazil_dashboard", base_dashboard)
    monkeypatch.setattr(brazil_dashboard_v2, "enrich_calendar_expectations", enrich)
    monkeypatch.setattr(brazil_dashboard_v2, "persist_event_expectations", fail_persistence)
    monkeypatch.setattr(brazil_dashboard_v2, "apply_cached_event_expectations", no_cached)

    result = asyncio.run(brazil_dashboard_v2.brazil_dashboard(FakeRepository()))

    assert result["calendar"][0]["expectation"] == expectation
    status = result["source_status"]["focus_event_expectations"]
    assert status["ready"] is True
    assert status["cache_persistence_error"] == "RuntimeError: D1 unavailable"
