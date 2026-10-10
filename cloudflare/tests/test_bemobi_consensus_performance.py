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
