from __future__ import annotations

import asyncio

import pytest

from src import bemobi_consensus


def test_independent_consensus_reads_run_concurrently(monkeypatch) -> None:
    started: list[str] = []
    all_started = asyncio.Event()

    async def read(name: str, result):
        started.append(name)
        if len(started) == 7:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=0.5)
        return result

    async def dashboard(_repository):
        return {"ready": True}

    monkeypatch.setattr(bemobi_consensus, "bemobi_dashboard", dashboard)
    monkeypatch.setattr(
        bemobi_consensus,
        "load_bemobi_facts",
        lambda _repository, fact_type: read(fact_type, []),
    )
    monkeypatch.setattr(
        bemobi_consensus,
        "latest_bemobi_fact",
        lambda _repository, fact_type: read(fact_type, None),
    )

    class Repository:
        async def all(self, _query):
            return await read("QUARTER_ACTUALS", [])

    result = asyncio.run(bemobi_consensus.bemobi_consensus(Repository()))

    assert set(started) == {
        "ANALYST",
        "FORWARD_CONSENSUS",
        "BEAT_MISS",
        "NEXT_QUARTER",
        "REFERENCE_MODEL",
        "RESULT",
        "QUARTER_ACTUALS",
    }
    assert result == {"ready": False, "reason": "bemobi_consensus_facts_not_ready"}


def test_consensus_read_errors_are_not_hidden(monkeypatch) -> None:
    async def dashboard(_repository):
        return {"ready": True}

    async def fail(_repository, _fact_type):
        raise RuntimeError("simulert databasefeil")

    monkeypatch.setattr(bemobi_consensus, "bemobi_dashboard", dashboard)
    monkeypatch.setattr(bemobi_consensus, "load_bemobi_facts", fail)
    monkeypatch.setattr(bemobi_consensus, "latest_bemobi_fact", fail)

    class Repository:
        async def all(self, _query):
            raise RuntimeError("simulert databasefeil")

    with pytest.raises(RuntimeError, match="simulert databasefeil"):
        asyncio.run(bemobi_consensus.bemobi_consensus(Repository()))


def test_consensus_history_parallel_reads_keep_order_and_reuse_report_date(monkeypatch) -> None:
    import bemobi_consensus_history as history

    initial = asyncio.Event()
    market = asyncio.Event()
    initial_reads = []
    market_reads = []
    dates = {"3Q26": "2026-11-12", "2Q26": "2026-08-11"}

    async def independent(name, value):
        initial_reads.append(name)
        if len(initial_reads) == 2:
            initial.set()
        await asyncio.wait_for(initial.wait(), timeout=0.5)
        return value

    async def metadata(_repository):
        return await independent("metadata", {
            period: {"result_date": day, "result_source": "Test", "result_source_url": None,
                     "model_revision": {}}
            for period, day in dates.items()
        })

    async def forward(_repository, current):
        return await independent("forward", {"current": current})

    async def reaction(_repository, day):
        market_reads.append(day)
        if len(market_reads) == 2:
            market.set()
        await asyncio.wait_for(market.wait(), timeout=0.5)
        return {"status": "OK", "result_date": day}

    monkeypatch.setattr(history, "_event_metadata", metadata)
    monkeypatch.setattr(history, "_forward_tracker", forward)
    monkeypatch.setattr(history, "_market_reaction", reaction)
    items = [{"period": period, "broker": broker}
             for period, broker in (("3Q26", "XP"), ("2Q26", "XP"), ("3Q26", "BTG"), ("unknown", "XP"))]
    result = asyncio.run(history.build_consensus_history(items, object(), current_forward=[{"year": 2027}]))
    assert set(initial_reads) == {"metadata", "forward"}
    assert market_reads == ["2026-11-12", "2026-08-11"]
    assert [event["period"] for event in result["events"]] == ["3Q26", "2Q26", "3Q26"]
    assert [event["expectation"]["broker"] for event in result["events"]] == ["XP", "XP", "BTG"]
    assert [event["market_reaction"]["result_date"] for event in result["events"]] == [
        "2026-11-12", "2026-08-11", "2026-11-12"]
    assert result["forward_revision_tracker"] == {"current": [{"year": 2027}]}


def test_consensus_history_read_error_is_not_hidden(monkeypatch) -> None:
    import bemobi_consensus_history as history

    async def fail(_repository):
        raise RuntimeError("simulert historikkfeil")

    async def forward(_repository, _current):
        return {}

    monkeypatch.setattr(history, "_event_metadata", fail)
    monkeypatch.setattr(history, "_forward_tracker", forward)
    with pytest.raises(RuntimeError, match="simulert historikkfeil"):
        asyncio.run(history.build_consensus_history([], object()))
