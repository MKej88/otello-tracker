from __future__ import annotations

import asyncio

import pytest

from src import bemobi_dashboard_base


def test_independent_bemobi_reads_run_concurrently(monkeypatch) -> None:
    started: list[str] = []
    all_started = asyncio.Event()

    async def read(name: str, result):
        started.append(name)
        if len(started) == 7:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=0.5)
        return result

    async def summary(_repository):
        return {"ready": True}

    async def enrich(value, _repository):
        return value

    monkeypatch.setattr(bemobi_dashboard_base, "dashboard_summary", summary)
    monkeypatch.setattr(bemobi_dashboard_base, "enrich_dashboard_summary", enrich)
    monkeypatch.setattr(
        bemobi_dashboard_base,
        "_latest_distribution",
        lambda _repository: read("distribution", None),
    )
    monkeypatch.setattr(
        bemobi_dashboard_base,
        "_latest_result_source",
        lambda _repository: read("result_source", None),
    )
    monkeypatch.setattr(
        bemobi_dashboard_base,
        "latest_bemobi_fact",
        lambda _repository, fact_type: read(fact_type, None),
    )
    monkeypatch.setattr(
        bemobi_dashboard_base,
        "load_bemobi_facts",
        lambda _repository, fact_type: read(fact_type, []),
    )

    result = asyncio.run(bemobi_dashboard_base.bemobi_dashboard(object()))

    assert set(started) == {
        "distribution",
        "result_source",
        "RESULT",
        "OWNERSHIP",
        "TTM_QUARTER",
        "VALUATION_ANCHOR",
        "NEXT_QUARTER",
    }
    assert result == {
        "ready": False,
        "reason": "bemobi_investor_facts_not_ready",
        "data_status": None,
    }


def test_bemobi_read_errors_are_not_hidden(monkeypatch) -> None:
    async def summary(_repository):
        return {"ready": True}

    async def enrich(value, _repository):
        return value

    async def fail(_repository):
        raise RuntimeError("simulert databasefeil")

    async def no_fact(_repository, _fact_type):
        return None

    async def no_facts(_repository, _fact_type):
        return []

    monkeypatch.setattr(bemobi_dashboard_base, "dashboard_summary", summary)
    monkeypatch.setattr(bemobi_dashboard_base, "enrich_dashboard_summary", enrich)
    monkeypatch.setattr(bemobi_dashboard_base, "_latest_distribution", fail)
    monkeypatch.setattr(bemobi_dashboard_base, "_latest_result_source", fail)
    monkeypatch.setattr(bemobi_dashboard_base, "latest_bemobi_fact", no_fact)
    monkeypatch.setattr(bemobi_dashboard_base, "load_bemobi_facts", no_facts)

    with pytest.raises(RuntimeError, match="simulert databasefeil"):
        asyncio.run(bemobi_dashboard_base.bemobi_dashboard(object()))
