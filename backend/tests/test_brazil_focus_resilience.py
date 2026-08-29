from __future__ import annotations

import asyncio
import json
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
            key, value, updated_at = params[:3]
            if "json_patch" in sql and (current := self.state.get(str(key))):
                current_payload = json.loads(current["value"])
                incoming_payload = json.loads(str(value))
                root = "expectations" if "expectations" in incoming_payload else "values"
                if root == "expectations":
                    event_key, incoming = next(iter(incoming_payload[root].items()))
                    path = (event_key,)
                    previous = current_payload.get(root, {}).get(event_key)
                else:
                    indicator, years = next(iter(incoming_payload[root].items()))
                    year, incoming = next(iter(years.items()))
                    path = (indicator, year)
                    previous = current_payload.get(root, {}).get(indicator, {}).get(year)
                previous_date = str(previous.get("survey_date") or "") if previous else ""
                incoming_date = str(incoming.get("survey_date") or "")
                if previous_date > incoming_date:
                    return {"success": True}
                if root == "expectations":
                    current_payload.setdefault(root, {})[path[0]] = incoming
                else:
                    current_payload.setdefault(root, {}).setdefault(path[0], {})[path[1]] = incoming
                current_payload.update(
                    {key: value for key, value in incoming_payload.items() if key != root}
                )
                value = json.dumps(current_payload)
            elif "json_extract" in sql and (current := self.state.get(str(key))):
                current_date = json.loads(current["value"]).get("survey_date") or ""
                incoming_date = json.loads(str(value)).get("survey_date") or ""
                if current_date > incoming_date:
                    return {"success": True}
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


def test_partial_live_focus_response_is_completed_from_merged_snapshot() -> None:
    repo = FakeRepository()
    asyncio.run(resolve_annual_focus(repo, _live_focus("2026-08-28"), as_of_date="2026-08-29"))
    partial = {
        "ready": True,
        "values": {"selic": {"2026": {"median": 13.25, "survey_date": "2026-08-29"}}},
    }

    focus, status = asyncio.run(
        resolve_annual_focus(repo, partial, as_of_date="2026-08-29")
    )

    assert focus["data_source"] == "BCB_OLINDA_LIVE"
    assert focus["fallback"] is False
    assert focus["values"]["selic"]["2026"]["median"] == 13.25
    assert focus["values"]["selic"]["2027"]["median"] == 11.75
    assert focus["values"]["ipca"]["2026"]["median"] == 4.95
    assert focus["values"]["gdp"]["2027"]["median"] == 1.50
    assert status["fallback"] is False


def test_first_partial_live_focus_is_completed_by_published_bootstrap() -> None:
    repo = FakeRepository()
    partial = {
        "ready": True,
        "values": {"selic": {"2026": {"median": 13.25, "survey_date": "2026-08-29"}}},
    }

    asyncio.run(resolve_annual_focus(repo, partial, as_of_date="2026-08-29"))
    fallback, _ = asyncio.run(
        resolve_annual_focus(repo, {"ready": False, "values": {}}, as_of_date="2026-08-30")
    )

    assert fallback["values"]["selic"]["2026"]["median"] == 13.25
    assert fallback["values"]["ipca"]["2027"]["median"] == 4.25
    assert fallback["values"]["gdp"]["2026"]["median"] == 1.95


def test_partial_cache_after_interrupted_write_is_completed_by_bootstrap() -> None:
    class InterruptingRepository(FakeRepository):
        def __init__(self) -> None:
            super().__init__()
            self.writes = 0
            self.interrupt_writes = True

        async def run(self, sql: str, params=()):
            self.writes += 1
            if self.interrupt_writes and self.writes == 2:
                raise RuntimeError("transient D1 write failure")
            return await super().run(sql, params)

    repo = InterruptingRepository()
    with pytest.raises(RuntimeError, match="transient D1 write failure"):
        asyncio.run(resolve_annual_focus(repo, _live_focus(), as_of_date="2026-08-29"))

    repo.interrupt_writes = False
    fallback, status = asyncio.run(
        resolve_annual_focus(repo, {"ready": False, "values": {}}, as_of_date="2026-08-30")
    )

    assert fallback["data_source"] == "LAST_GOOD_D1_CACHE"
    assert fallback["values"]["selic"]["2026"]["median"] == 13.75
    assert fallback["values"]["selic"]["2027"]["median"] == 12.0
    assert fallback["values"]["ipca"]["2026"]["median"] == 5.02
    assert fallback["values"]["gdp"]["2027"]["median"] == 1.5
    assert fallback["values"]["usd_brl"]["2027"]["median"] == 5.3
    assert status["fallback_source"] == "LAST_GOOD_D1_CACHE"


def test_older_concurrent_focus_write_cannot_replace_newer_snapshot() -> None:
    repo = FakeRepository()
    newer = _live_focus("2026-08-29")
    older = _live_focus("2026-08-28")

    async def race() -> None:
        # Model the harmful write order: the historical request reaches D1 last.
        await resolve_annual_focus(repo, newer, as_of_date="2026-08-29")
        await resolve_annual_focus(repo, older, as_of_date="2026-08-29")

    asyncio.run(race())
    fallback, _ = asyncio.run(
        resolve_annual_focus(repo, {"ready": False, "values": {}}, as_of_date="2026-08-30")
    )
    assert fallback["values"]["selic"]["2026"]["survey_date"] == "2026-08-29"


def test_equal_date_concurrent_focus_writes_preserve_distinct_years() -> None:
    repo = FakeRepository()
    first = {
        "ready": True,
        "values": {"selic": {"2026": {"median": 13.5, "survey_date": "2026-08-28"}}},
    }
    second = {
        "ready": True,
        "values": {"selic": {"2028": {"median": 10.0, "survey_date": "2026-08-28"}}},
    }

    async def race() -> None:
        await asyncio.gather(
            resolve_annual_focus(repo, first, as_of_date="2026-08-29"),
            resolve_annual_focus(repo, second, as_of_date="2026-08-29"),
        )

    asyncio.run(race())
    cached = json.loads(repo.state["brazil_focus_annual_v1"]["value"])

    assert cached["values"]["selic"]["2026"]["median"] == 13.5
    assert cached["values"]["selic"]["2028"]["median"] == 10.0


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


def test_concurrent_event_writes_preserve_keys_and_newest_shared_survey() -> None:
    repo = FakeRepository()

    def event(name: str, survey_date: str, value: float) -> dict:
        return {
            "date": "2026-09-11",
            "name": name,
            "reference": "aug. 2026",
            "expectation": {
                "event_consensus": True,
                "survey_date": survey_date,
                "value": value,
            },
        }

    async def race() -> None:
        # The older request deliberately reaches the shared event last.
        await persist_event_expectations(
            repo,
            [event("IPCA", "2026-08-29", 0.31), event("GDP", "2026-08-29", 0.4)],
        )
        await persist_event_expectations(
            repo,
            [event("IPCA", "2026-08-28", 0.35), event("Selic", "2026-08-28", 13.75)],
        )

    asyncio.run(race())
    cached = json.loads(repo.state["brazil_focus_event_expectations_v1"]["value"])

    assert len(cached["expectations"]) == 3
    assert cached["expectations"]["2026-09-11|IPCA|aug. 2026"]["value"] == 0.31


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


def test_failed_cache_read_does_not_discard_live_consensus(monkeypatch: pytest.MonkeyPatch) -> None:
    event = {"date": "2026-09-11", "name": "IPCA", "reference": "aug. 2026"}
    expectation = {"event_consensus": True, "value": 0.31, "provider": "BCB Focus"}

    async def base_dashboard(*_args, **_kwargs):
        return {
            "as_of_date": "2026-08-29",
            "focus": {"ready": False, "values": {}},
            "calendar": [event],
            "source_status": {"focus": {"ready": False}},
        }

    async def enrich(rows, **_kwargs):
        return [dict(rows[0], expectation=expectation)], {"ready": True}

    async def fail_cache_read(*_args, **_kwargs):
        raise RuntimeError("runtime_state unavailable")

    monkeypatch.setattr(brazil_dashboard_v2.base, "brazil_dashboard", base_dashboard)
    monkeypatch.setattr(brazil_dashboard_v2, "enrich_calendar_expectations", enrich)
    monkeypatch.setattr(brazil_dashboard_v2, "apply_cached_event_expectations", fail_cache_read)

    result = asyncio.run(brazil_dashboard_v2.brazil_dashboard(FakeRepository()))

    assert result["calendar"][0]["expectation"] == expectation
    status = result["source_status"]["focus_event_expectations"]
    assert status["ready"] is True
    assert status["cache_restore_error"] == "RuntimeError: runtime_state unavailable"
