from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import dashboard_hot_snapshot as hot  # noqa: E402


class FakeRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, str]] = {}
        self.writes = 0

    async def first(self, sql: str, parameters: tuple = ()):
        assert "runtime_state" in sql
        key = str(parameters[0])
        row = self.rows.get(key)
        return dict(row) if row is not None else None

    async def run(self, sql: str, parameters: tuple = ()):
        assert "runtime_state" in sql
        key, value, updated_at = parameters
        self.rows[str(key)] = {"value": str(value), "updated_at": str(updated_at)}
        self.writes += 1
        return {"success": True}


def test_hot_snapshot_builds_and_round_trips_exact_components(monkeypatch) -> None:
    repository = FakeRepository()
    calls: list[str] = []

    async def fake_summary(_repository):
        calls.append("summary")
        return {"ready": True, "as_of_date": "2026-08-22", "nav_per_share": 31.5}

    async def fake_enrich(summary, _repository):
        calls.append("enrich")
        return {**summary, "data_status": "GOOD"}

    async def fake_economic(_repository):
        calls.append("economic")
        return {"ready": True, "nav_per_share": 32.1}

    async def fake_quotes(_repository):
        calls.append("quotes")
        return {"ready": True, "symbols": {"OTEC": {"ready": True, "last": 24.0}}}

    async def fake_forecast(_repository):
        calls.append("forecast")
        return {"ready": True, "status": "READY", "estimate": {"base_case_shares": 1000}}

    monkeypatch.setattr(hot, "dashboard_summary", fake_summary)
    monkeypatch.setattr(hot, "enrich_dashboard_summary", fake_enrich)
    monkeypatch.setattr(hot, "economic_nav_summary", fake_economic)
    monkeypatch.setattr(hot, "market_quote_details", fake_quotes)
    monkeypatch.setattr(hot, "buyback_forecast", fake_forecast)

    result = asyncio.run(hot.refresh_dashboard_hot_snapshot(repository, force=True))

    assert result["status"] == "ok"
    assert result["components"] == ["economic", "forecast", "quotes", "summary"]
    assert result["bytes"] > 0
    assert repository.writes == 1
    assert calls == ["summary", "enrich", "economic", "quotes", "forecast"]

    snapshot = asyncio.run(hot.load_dashboard_hot_snapshot(repository))
    assert snapshot is not None
    assert snapshot["version"] == hot.SNAPSHOT_VERSION
    assert snapshot["summary"]["nav_per_share"] == 31.5
    assert snapshot["economic"]["nav_per_share"] == 32.1
    assert snapshot["quotes"]["symbols"]["OTEC"]["last"] == 24.0
    assert snapshot["forecast"]["estimate"]["base_case_shares"] == 1000

    for component in ("summary", "economic", "quotes", "forecast"):
        value = asyncio.run(hot.dashboard_hot_component(repository, component))
        assert value == snapshot[component]


def test_existing_snapshot_skips_expensive_rebuild_when_not_forced(monkeypatch) -> None:
    repository = FakeRepository()
    existing = {
        "version": hot.SNAPSHOT_VERSION,
        "generated_at": "2026-08-23T08:00:00.000Z",
        "summary": {"ready": True},
        "economic": {"ready": True},
        "quotes": {"ready": True},
        "forecast": {"ready": True},
    }
    repository.rows[hot.STATE_KEY] = {
        "value": json.dumps(existing),
        "updated_at": existing["generated_at"],
    }

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("expensive hot-snapshot calculation should have been skipped")

    monkeypatch.setattr(hot, "dashboard_summary", must_not_run)
    monkeypatch.setattr(hot, "economic_nav_summary", must_not_run)
    monkeypatch.setattr(hot, "market_quote_details", must_not_run)
    monkeypatch.setattr(hot, "buyback_forecast", must_not_run)

    result = asyncio.run(hot.refresh_dashboard_hot_snapshot(repository, force=False))

    assert result == {
        "status": "skipped",
        "reason": "inputs_unchanged",
        "generated_at": existing["generated_at"],
    }
    assert repository.writes == 0


def test_invalid_or_old_snapshot_is_ignored() -> None:
    repository = FakeRepository()
    repository.rows[hot.STATE_KEY] = {"value": "not-json", "updated_at": "x"}
    assert asyncio.run(hot.load_dashboard_hot_snapshot(repository)) is None

    repository.rows[hot.STATE_KEY] = {
        "value": json.dumps(
            {
                "version": hot.SNAPSHOT_VERSION + 1,
                "summary": {},
                "economic": {},
                "quotes": {},
                "forecast": {},
            }
        ),
        "updated_at": "x",
    }
    assert asyncio.run(hot.load_dashboard_hot_snapshot(repository)) is None


def test_unknown_component_is_rejected() -> None:
    repository = FakeRepository()
    try:
        asyncio.run(hot.dashboard_hot_component(repository, "unknown"))
    except ValueError as exc:
        assert "Unknown dashboard hot-snapshot component" in str(exc)
    else:
        raise AssertionError("unknown hot-snapshot component must be rejected")
