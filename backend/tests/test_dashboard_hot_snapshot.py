from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.main import _sync_summary_with_otec_quote

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import dashboard_hot_snapshot as hot  # noqa: E402


class FakeRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, str]] = {}
        self.reads = 0
        self.writes = 0

    async def first(self, sql: str, parameters: tuple = ()):
        assert "runtime_state" in sql
        self.reads += 1
        key = str(parameters[0])
        row = self.rows.get(key)
        return dict(row) if row is not None else None

    async def run(self, sql: str, parameters: tuple = ()):
        assert "runtime_state" in sql
        key, value, updated_at = parameters
        self.rows[str(key)] = {"value": str(value), "updated_at": str(updated_at)}
        self.writes += 1
        return {"success": True}


def current_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def test_worker_otec_sync_matches_reference_summary() -> None:
    summary = {
        "nav_per_share": 23.65,
        "otec_price": 17.84,
        "nav_discount_pct": 24.57,
        "changes": {"otec_pct": -0.5, "discount_pp": 0.4},
        "nav_discount_insights": {
            "nav_per_share": 23.65,
            "share_price": 17.84,
            "discount_pct": 24.57,
            "upside_to_nav_pct": 32.57,
            "month_change_pp": 1.2,
            "range_1y": {"low": 20.0, "high": 30.0, "position_pct": 45.7},
        },
    }
    quote = {
        "ready": True,
        "last": 17.98,
        "last_price_type": "CLOSE",
        "trading_date": "2026-09-04",
        "last_updated_at": "2026-09-04T16:20:00+02:00",
        "source": "EURONEXT",
        "changes": {"daily_pct": -0.11},
    }

    assert hot.sync_otec_price(summary, quote) == _sync_summary_with_otec_quote(
        summary, quote
    )


def test_hot_snapshot_builds_and_round_trips_exact_components(monkeypatch) -> None:
    repository = FakeRepository()
    calls: list[str] = []
    started = {
        "summary": asyncio.Event(),
        "economic": asyncio.Event(),
        "quotes": asyncio.Event(),
        "buyback": asyncio.Event(),
        "events": asyncio.Event(),
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
        return {
            "ready": True,
            "symbols": {
                "OTEC": {
                    "ready": True,
                    "last": 24.0,
                    "changes": {"daily_pct": 1.5},
                }
            },
        }

    async def fake_buyback(_repository):
        calls.append("buyback")
        await mark_started("buyback")
        return {
            "ready": True,
            "status": "READY",
            "estimate": {"base_case_shares": 1000},
        }

    async def fake_events(_repository):
        calls.append("events")
        await mark_started("events")
        return {"ready": True, "events": [], "calendar": []}

    monkeypatch.setattr(hot, "dashboard_summary", fake_summary)
    monkeypatch.setattr(hot, "enrich_dashboard_summary", fake_enrich)
    monkeypatch.setattr(hot, "economic_nav_summary", fake_economic)
    monkeypatch.setattr(hot, "market_quote_details", fake_quotes)
    monkeypatch.setattr(hot, "buyback_overview_status", fake_buyback)
    monkeypatch.setattr(hot, "overview_events", fake_events)

    result = asyncio.run(hot.refresh_dashboard_hot_snapshot(repository, force=True))

    assert result["status"] == "ok"
    assert result["components"] == ["buyback", "economic", "events", "quotes", "summary"]
    assert result["bytes"] > 0
    assert repository.writes == 1
    assert set(calls[:5]) == {"summary", "economic", "quotes", "buyback", "events"}
    assert calls[-1] == "enrich"

    snapshot = asyncio.run(hot.load_dashboard_hot_snapshot(repository))
    assert snapshot is not None
    assert snapshot["version"] == hot.SNAPSHOT_VERSION
    assert snapshot["summary"]["nav_per_share"] == 31.5
    assert snapshot["summary"]["otec_price"] == 24.0
    assert snapshot["economic"]["nav_per_share"] == 32.1
    assert snapshot["economic"]["otec_price"] == 24.0
    assert snapshot["economic"]["calculated_at"] == "2026-08-23T23:59:59Z"
    assert snapshot["economic"]["calculated_at"] != snapshot["generated_at"]
    assert snapshot["quotes"]["symbols"]["OTEC"]["last"] == 24.0
    assert snapshot["buyback"]["estimate"]["base_case_shares"] == 1000
    assert snapshot["events"]["ready"] is True

    for component in ("summary", "economic", "quotes", "buyback", "events"):
        value = asyncio.run(hot.dashboard_hot_component(repository, component))
        assert value == snapshot[component]


def test_hot_components_share_one_snapshot_read() -> None:
    repository = FakeRepository()
    existing = {
        "version": hot.SNAPSHOT_VERSION,
        "generated_at": current_timestamp(),
        "summary": {"ready": True},
        "economic": {"ready": True},
        "quotes": {"ready": True},
        "buyback": {"ready": True},
        "events": {"ready": True, "events": [], "calendar": []},
    }
    repository.rows[hot.STATE_KEY] = {
        "value": json.dumps(existing),
        "updated_at": existing["generated_at"],
    }

    summary, quotes = asyncio.run(
        hot.dashboard_hot_components(repository, "summary", "quotes")
    )

    assert summary == existing["summary"]
    assert quotes == existing["quotes"]
    assert repository.reads == 1


def test_existing_snapshot_skips_expensive_rebuild_when_not_forced(monkeypatch) -> None:
    repository = FakeRepository()
    existing = {
        "version": hot.SNAPSHOT_VERSION,
        "generated_at": current_timestamp(),
        "summary": {"ready": True},
        "economic": {"ready": True},
        "quotes": {"ready": True},
        "buyback": {"ready": True},
        "events": {"ready": True, "events": [], "calendar": []},
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
    monkeypatch.setattr(hot, "buyback_overview_status", must_not_run)
    monkeypatch.setattr(hot, "overview_events", must_not_run)

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
        "generated_at": current_timestamp(),
        "summary": {"ready": True, "nav_per_share": 31.5},
        "economic": {"ready": True, "nav_per_share": 32.1},
        "quotes": {"ready": True, "symbols": {"OTEC": {"last": 24.0}}},
        "buyback": {"ready": True, "status": "READY"},
        "events": {"ready": True, "events": [], "calendar": []},
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
    monkeypatch.setattr(hot, "buyback_overview_status", must_not_run)
    monkeypatch.setattr(hot, "overview_events", must_not_run)

    result = asyncio.run(hot.dashboard_bootstrap_payload(repository))

    assert result["summary"] == existing["summary"]
    assert result["economic"] == existing["economic"]
    assert result["quotes"] == existing["quotes"]
    assert result["buyback"] == existing["buyback"]
    assert result["events"] == existing["events"]
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
        "buyback": {"ready": True},
        "events": {"ready": True, "events": [], "calendar": []},
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
    assert status["components"] == ["buyback", "economic", "events", "quotes", "summary"]
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
        "buyback": {},
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


def test_stale_snapshot_is_ignored_and_reported() -> None:
    repository = FakeRepository()
    generated_at = "2026-08-23T08:00:00.000Z"
    repository.rows[hot.STATE_KEY] = {
        "value": json.dumps(
            {
                "version": hot.SNAPSHOT_VERSION,
                "generated_at": generated_at,
                "summary": {"ready": True},
                "economic": {"ready": True},
                "quotes": {"ready": True},
                "buyback": {"ready": True},
                "events": {"ready": True, "events": [], "calendar": []},
            }
        ),
        "updated_at": generated_at,
    }
    now = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)

    assert asyncio.run(hot.load_dashboard_hot_snapshot(repository, now=now)) is None
    status = asyncio.run(hot.dashboard_hot_snapshot_status(repository, now=now))

    assert status["cache_status"] == "MISS"
    assert status["valid"] is False
    assert status["reason"] == "stale"
    assert status["age_seconds"] == 7200
    assert status["max_age_seconds"] == hot.SNAPSHOT_MAX_AGE_SECONDS


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
                "buyback": {},
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


def test_legacy_snapshot_calendar_titles_are_normalized_without_changing_data() -> None:
    repository = FakeRepository()
    payment = {
        "id": "action-20-payment_date", "company": "Bemobi",
        "title": "Betalingsdato for JCP", "date": "2026-11-30",
        "category": "DISTRIBUTION", "confirmed": True, "source": "Bemobi IR",
    }
    ex_date = {**payment, "id": "action-20-ex_date", "date": "2026-11-18",
               "title": "Ex-dato for JCP"}
    other = {**payment, "id": "action-21-payment_date", "title": "Betalingsdato for utbytte"}
    existing = {
        "version": hot.SNAPSHOT_VERSION, "generated_at": current_timestamp(),
        "summary": {"ready": True}, "economic": {"ready": True},
        "quotes": {"ready": True}, "buyback": {"ready": True},
        "events": {"ready": True, "events": [payment, ex_date, other], "calendar": []},
    }
    stored = json.dumps(existing)
    repository.rows[hot.STATE_KEY] = {
        "value": stored, "updated_at": existing["generated_at"],
    }
    expected = [
        {**payment, "title": "Utbetaling av renter på egenkapital"},
        {**ex_date, "title": "Ex-dato for renter på egenkapital"},
        other,
    ]
    component = asyncio.run(hot.dashboard_hot_component(repository, "events"))
    assert component is not None
    assert component["events"] == expected
    bootstrap = asyncio.run(hot.dashboard_bootstrap_payload(repository))
    assert bootstrap["events"]["events"] == expected
    assert repository.rows[hot.STATE_KEY]["value"] == stored
    assert repository.writes == 0


def _snapshot_fixture(now):
    return {
        "version": hot.SNAPSHOT_VERSION,
        "generated_at": now.isoformat(),
        **{name: {"ready": True} for name in hot._COMPONENTS},
    }


@pytest.mark.parametrize("component", sorted(hot._COMPONENTS))
@pytest.mark.parametrize("bad_value", [None, [], "invalid", 42, False])
def test_invalid_component_rejected_by_all_snapshot_read_paths(component, bad_value, monkeypatch):
    now = datetime.now(UTC)
    repository = FakeRepository()
    payload = _snapshot_fixture(now)
    payload[component] = bad_value
    repository.rows[hot.STATE_KEY] = {"value": json.dumps(payload), "updated_at": now.isoformat()}

    async def rebuild(_repository):
        return _snapshot_fixture(now)

    monkeypatch.setattr(hot, "build_dashboard_hot_snapshot", rebuild)
    assert asyncio.run(hot.load_dashboard_hot_snapshot(repository, now=now)) is None
    status = asyncio.run(hot.dashboard_hot_snapshot_status(repository, now=now))
    assert status["valid"] is False
    assert status["reason"] == "missing_or_invalid_components"
    assert asyncio.run(hot.dashboard_hot_component(repository, component)) is None
    assert asyncio.run(hot.dashboard_hot_components(repository, "summary", "quotes")) == (None, None)
    result = asyncio.run(hot.dashboard_bootstrap_payload(repository))
    assert result["meta"]["source"] == "live_fallback"
    assert result[component] == {"ready": True}
    assert repository.writes == 0


@pytest.mark.parametrize("age,valid,reason", [
    (-0.001, False, "generated_at_in_future"),
    (0, True, None),
    (5399.999, True, None),
    (5400, True, None),
    (5400.001, False, "stale"),
])
def test_serving_and_diagnostics_agree_at_subsecond_age_boundaries(age, valid, reason):
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    generated = now - timedelta(seconds=age)
    repository = FakeRepository()
    payload = _snapshot_fixture(generated)
    repository.rows[hot.STATE_KEY] = {"value": json.dumps(payload), "updated_at": generated.isoformat()}
    assert (asyncio.run(hot.load_dashboard_hot_snapshot(repository, now=now)) is not None) is valid
    status = asyncio.run(hot.dashboard_hot_snapshot_status(repository, now=now))
    assert status["valid"] is valid
    assert status["cache_status"] == ("HIT" if valid else "MISS")
    assert status["reason"] == reason
