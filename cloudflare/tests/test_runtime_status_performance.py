from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from src import runtime_status


def test_independent_runtime_status_reads_run_concurrently(monkeypatch) -> None:
    started: list[str] = []
    all_started = asyncio.Event()

    async def read(name: str, result):
        started.append(name)
        if len(started) == 7:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=0.5)
        return result

    monkeypatch.setattr(
        runtime_status,
        "_latest_job",
        lambda _repository, job: read(f"job:{job}", None),
    )
    monkeypatch.setattr(
        runtime_status,
        "_writer_lock",
        lambda _repository: read("writer_lock", None),
    )
    monkeypatch.setattr(
        runtime_status,
        "_latest_norges_bank_health",
        lambda _repository: read("norges_bank_health", None),
    )
    monkeypatch.setattr(
        runtime_status,
        "norges_bank_fx_coverage",
        lambda _repository: read("fx", {}),
    )
    monkeypatch.setattr(
        runtime_status,
        "dashboard_hot_snapshot_status",
        lambda _repository, *, now: read("hot_snapshot", {}),
    )
    monkeypatch.setattr(
        runtime_status,
        "_current_dashboard_quality",
        lambda _repository: read("dashboard_quality", {"status": "OK", "reasons": []}),
    )

    result = asyncio.run(
        runtime_status.runtime_status_summary(
            object(), now=datetime(2026, 9, 19, tzinfo=UTC)
        )
    )

    assert len(started) == 7
    assert result["status"] == "DOWN"


def test_runtime_status_still_propagates_read_errors(monkeypatch) -> None:
    async def fail(*_args, **_kwargs):
        raise RuntimeError("simulert databasefeil")

    monkeypatch.setattr(runtime_status, "_latest_job", fail)

    with pytest.raises(RuntimeError, match="simulert databasefeil"):
        asyncio.run(runtime_status.runtime_status_summary(object()))
