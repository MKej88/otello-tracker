from __future__ import annotations

import asyncio
from decimal import Decimal

import bemobi_receivable_history_repair as repair


class FakeRepository:
    def __init__(self, dates=("2026-11-18", "2026-11-19")):
        self.zero_days = set(dates)
        self.reads = []
        self.writes = []
        self.materialized = []

    async def all(self, sql, params=()):
        assert "FROM other_net_assets_daily_estimates o" in sql
        assert "n.nav_scope='FULL'" in sql
        assert params[0] == repair.FULL_CALCULATION_VERSION
        from datetime import date, timedelta
        assert params[1] == (date.fromisoformat(params[2]) - timedelta(days=21)).isoformat()
        assert params[2] in {"2026-11-21", "2026-11-29"}
        return [{"estimate_date": d, "associated_receivable_nok": "0"}
                for d in sorted(self.zero_days)]

    async def first(self, sql, params=()):
        assert "SELECT associated_receivable_nok" in sql
        self.reads.append(params[0])
        if params[0] in self.zero_days:
            return {"associated_receivable_nok": "0"}
        return {"associated_receivable_nok": "10319333.091227880720"}


def _action():
    return {
        "id": 20, "ex_date": "2026-11-18", "payment_date": "2026-11-30",
        "source_document_id": 88,
    }


def _setup(monkeypatch, repo, *, actions=None, fx_ready=True, history_ready=True):
    events = []
    async def get_actions(repository):
        assert repository is repo
        return [_action()] if actions is None else actions

    async def expected(repository, day, selected):
        assert repository is repo and len(selected) == 1
        events.append(("expected", day))
        if not fx_ready:
            return None
        return (
            Decimal("10319333.091227880720"), "ESTIMATED_GROSS",
            [{"corporate_action_id": 20}],
        )

    async def ona(repository, day):
        assert repository is repo
        assert day in repo.zero_days
        events.append(("ona", day))
        repo.zero_days.remove(day)
        return {"status": "ok", "dirty": True}

    async def full(repository, day):
        assert repository is repo
        events.append(("full", day))
        return {"status": "ok", "dirty": True}

    async def estimated(repository, day):
        assert repository is repo
        events.append(("estimated", day))
        return {"ready": history_ready, "reason": "missing_source" if not history_ready else None}

    async def materialize(repository, day, point):
        assert repository is repo and point.get("ready") is True
        events.append(("materialize", day))
        repo.materialized.append(day)

    monkeypatch.setattr(repair, "_receivable_actions", get_actions)
    monkeypatch.setattr(repair, "_receivable_for_day", expected)
    monkeypatch.setattr(repair, "refresh_other_net_assets_if_dirty", ona)
    monkeypatch.setattr(repair, "refresh_full_nav_if_dirty", full)
    monkeypatch.setattr(repair, "_estimated_point", estimated)
    monkeypatch.setattr(repair, "_write_point_and_remove_retry", materialize)
    return events


def test_replays_missing_ex_date_and_next_day_via_existing_nav_model(monkeypatch):
    repo = FakeRepository()
    events = _setup(monkeypatch, repo)
    result = asyncio.run(repair.repair_late_bemobi_receivable_history(
        repo, target_date="2026-11-21",
    ))
    assert result["status"] == "ok"
    assert result["attempted"] == 2
    assert [x["date"] for x in result["repaired"]] == ["2026-11-18", "2026-11-19"]
    assert all(x["receivable_nok"] == "10319333.091227880720" for x in result["repaired"])
    assert events == [
        (kind, day) for day in ("2026-11-18", "2026-11-19")
        for kind in ("expected", "ona", "full", "estimated", "materialize")
    ]
    assert repo.materialized == ["2026-11-18", "2026-11-19"]
    assert asyncio.run(repair.repair_late_bemobi_receivable_history(
        repo, target_date="2026-11-21",
    ))["attempted"] == 0


def test_does_not_repair_unproven_action_or_unready_historical_rate(monkeypatch):
    repo = FakeRepository()
    events = _setup(monkeypatch, repo, actions=[])
    first = asyncio.run(repair.repair_late_bemobi_receivable_history(
        repo, target_date="2026-11-21",
    ))
    assert first["status"] == "ok"
    assert first["repaired"] == [] and not events

    events = _setup(monkeypatch, repo, fx_ready=False)
    second = asyncio.run(repair.repair_late_bemobi_receivable_history(
        repo, target_date="2026-11-21",
    ))
    assert second["status"] == "partial"
    assert [x["reason"] for x in second["errors"]] == ["missing_brl_nok", "missing_brl_nok"]
    assert repo.zero_days == {"2026-11-18", "2026-11-19"}
    assert all(e[0] == "expected" for e in events)


def test_never_replays_unbounded_history_or_unready_estimated_history(monkeypatch):
    repo = FakeRepository(tuple(f"2026-11-{d:02}" for d in range(18, 30)))
    events = _setup(monkeypatch, repo)
    result = asyncio.run(repair.repair_late_bemobi_receivable_history(
        repo, target_date="2026-11-29",
    ))
    assert result["status"] == "partial"
    assert result["reason"] == "bounded_replay_limit"
    assert repo.materialized == [] and not events

    repo = FakeRepository(("2026-11-18",))
    events = _setup(monkeypatch, repo, history_ready=False)
    fail = asyncio.run(repair.repair_late_bemobi_receivable_history(
        repo, target_date="2026-11-21",
    ))
    assert fail["status"] == "partial"
    assert fail["errors"][0]["reason"] == "estimated_history_not_ready"
    assert events[-1] == ("estimated", "2026-11-18")
    assert repo.materialized == []
