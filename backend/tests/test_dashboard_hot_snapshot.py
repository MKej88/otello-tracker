from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
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
    started = {
        "summary": asyncio.Event(),
        "economic": asyncio.Event(),
        "quotes": asyncio.Event(),
        "forecast": asyncio.Event(),
    }

    async def mark_started(component: str) -> None:
        started[component].set()
        await asyncio.gather(*(event.wait() for event in started.values()))

    async def fake_summary(_repository):
        calls.append("summary")
        await mark_started("summary")
        return {"ready": True, "as_of_date": "2026-08-22", "nav_per_share": 31.5}

    async def fake_enrich(summary, _repository):
        calls.append("enrich")
        return {**summary, "data_status": "GOOD"}

    async def fake_economic(_repository):
        calls.append("economic")
        await mark_started("economic")
        return {
            "ready": True,
            "nav_per_share": 32.1,
            "calculated_at": "2026-08-23T23:59:59Z",
        }

    async def fake_quotes(_repository):
        calls.append("quotes")
        await mark_started("quotes")
        return {"ready": True, "symbols": {"OTEC": {"ready": True, "last": 24.0}}}

    async def fake_forecast(_repository):
        calls.append("forecast")
        await mark_started("forecast")
        return {
            "ready": True,
            "status": "READY",
            "estimate": {"base_case_shares": 1000},
        }

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
    assert set(calls[:4]) == {"summary", "economic", "quotes", "forecast"}
    assert calls[-1] == "enrich"

    snapshot = asyncio.run(hot.load_dashboard_hot_snapshot(repository))
    assert snapshot is not None
    assert snapshot["version"] == hot.SNAPSHOT_VERSION
    assert snapshot["summary"]["nav_per_share"] == 31.5
    assert snapshot["economic"]["nav_per_share"] == 32.1
    assert snapshot["economic"]["calculated_at"] == snapshot["generated_at"]
    assert snapshot["economic"]["calculated_at"] != "2026-08-23T23:59:59Z"
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
        raise AssertionError(
            "expensive hot-snapshot calculation should have been skipped"
        )

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


def test_dashboard_bootstrap_reuses_hot_snapshot_without_rebuild(monkeypatch) -> None:
    repository = FakeRepository()
    existing = {
        "version": hot.SNAPSHOT_VERSION,
        "generated_at": "2026-08-23T16:00:00.000Z",
        "summary": {"ready": True, "nav_per_share": 31.5},
        "economic": {"ready": True, "nav_per_share": 32.1},
        "quotes": {"ready": True, "symbols": {"OTEC": {"last": 24.0}}},
        "forecast": {"ready": True, "status": "READY"},
    }
    repository.rows[hot.STATE_KEY] = {
        "value": json.dumps(existing),
        "updated_at": existing["generated_at"],
    }

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("bootstrap should reuse the persisted hot snapshot")

    monkeypatch.setattr(hot, "dashboard_summary", must_not_run)
    monkeypatch.setattr(hot, "economic_nav_summary", must_not_run)
    monkeypatch.setattr(hot, "market_quote_details", must_not_run)
    monkeypatch.setattr(hot, "buyback_forecast", must_not_run)

    result = asyncio.run(hot.dashboard_bootstrap_payload(repository))

    assert result["summary"] == existing["summary"]
    assert result["economic"] == existing["economic"]
    assert result["quotes"] == existing["quotes"]
    assert result["forecast"] == existing["forecast"]
    assert result["meta"]["source"] == "hot_snapshot"
    assert result["meta"]["snapshot_version"] == hot.SNAPSHOT_VERSION
    assert result["meta"]["generated_at"] == existing["generated_at"]
    assert result["meta"]["server_ms"] >= 0
    assert repository.writes == 0


def test_hot_snapshot_status_reports_hit_age_size_and_components() -> None:
    repository = FakeRepository()
    existing = {
        "version": hot.SNAPSHOT_VERSION,
        "generated_at": "2026-08-23T08:00:00.000Z",
        "summary": {"ready": True},
        "economic": {"ready": True},
        "quotes": {"ready": True},
        "forecast": {"ready": True},
    }
    encoded = json.dumps(existing)
    repository.rows[hot.STATE_KEY] = {
        "value": encoded,
        "updated_at": existing["generated_at"],
    }

    status = asyncio.run(
        hot.dashboard_hot_snapshot_status(
            repository,
            now=datetime(2026, 8, 23, 8, 5, tzinfo=UTC),
        )
    )

    assert status["cache_status"] == "HIT"
    assert status["available"] is True
    assert status["valid"] is True
    assert status["state_key"] == hot.STATE_KEY
    assert status["expected_version"] == hot.SNAPSHOT_VERSION
    assert status["stored_version"] == hot.SNAPSHOT_VERSION
    assert status["generated_at"] == existing["generated_at"]
    assert status["age_seconds"] == 300
    assert status["bytes"] == len(encoded.encode("utf-8"))
    assert status["components"] == ["economic", "forecast", "quotes", "summary"]
    assert status["reason"] is None


def test_hot_snapshot_status_reports_missing_and_version_mismatch() -> None:
    repository = FakeRepository()
    missing = asyncio.run(hot.dashboard_hot_snapshot_status(repository))
    assert missing["cache_status"] == "MISS"
    assert missing["available"] is False
    assert missing["valid"] is False
    assert missing["reason"] == "missing"

    old = {
        "version": hot.SNAPSHOT_VERSION - 1,
        "generated_at": "2026-08-23T08:00:00.000Z",
        "summary": {},
        "economic": {},
        "quotes": {},
        "forecast": {},
    }
    repository.rows[hot.STATE_KEY] = {
        "value": json.dumps(old),
        "updated_at": old["generated_at"],
    }
    mismatch = asyncio.run(
        hot.dashboard_hot_snapshot_status(
            repository,
            now=datetime(2026, 8, 23, 8, 5, tzinfo=UTC),
        )
    )
    assert mismatch["cache_status"] == "MISS"
    assert mismatch["available"] is True
    assert mismatch["valid"] is False
    assert mismatch["stored_version"] == hot.SNAPSHOT_VERSION - 1
    assert mismatch["reason"] == "version_mismatch"


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
