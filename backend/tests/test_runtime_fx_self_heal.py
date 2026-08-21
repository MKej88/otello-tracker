from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src import fx_freshness  # noqa: E402
from src.runtime_status import runtime_status_summary  # noqa: E402


class FakeRepository:
    def __init__(self, *, brl_date: str | None, usd_date: str | None) -> None:
        self.fx = {"BRL": brl_date, "USD": usd_date}

    async def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if "FROM fx_rates" not in sql:
            return []
        return [
            {
                "base_currency": currency,
                "latest_date": latest_date,
                "latest_fetch": "2026-08-21T05:40:00Z",
            }
            for currency, latest_date in self.fx.items()
            if latest_date is not None
        ]

    async def first(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        if "FROM job_runs" in sql:
            job_name = params[0]
            if job_name == "cloudflare_full_refresh":
                return {
                    "id": 10,
                    "job_name": job_name,
                    "started_at": "2026-08-21T03:35:00Z",
                    "finished_at": "2026-08-21T03:44:00Z",
                    "status": "SUCCESS",
                    "records_written": 20,
                    "error_message": None,
                    "metadata_json": '{"target_date":"2026-08-20"}',
                }
            if job_name == "cloudflare_fast_refresh":
                return {
                    "id": 11,
                    "job_name": job_name,
                    "started_at": "2026-08-21T06:00:00Z",
                    "finished_at": "2026-08-21T06:00:05Z",
                    "status": "SUCCESS",
                    "records_written": 2,
                    "error_message": None,
                    "metadata_json": "{}",
                }
        if "FROM source_health" in sql:
            return {
                "checked_at": "2026-08-21T03:44:00Z",
                "status": "OK",
                "error_message": None,
                "metadata_json": "{}",
            }
        return None


def test_expected_norges_bank_date_uses_previous_trading_day() -> None:
    friday = datetime(2026, 8, 21, 6, 0, tzinfo=UTC)
    monday = datetime(2026, 8, 24, 6, 0, tzinfo=UTC)
    assert fx_freshness.expected_norges_bank_date(friday) == "2026-08-20"
    assert fx_freshness.expected_norges_bank_date(monday) == "2026-08-21"


def test_fast_fx_repair_skips_network_when_current(monkeypatch) -> None:
    repository = FakeRepository(brl_date="2026-08-20", usd_date="2026-08-20")

    async def unexpected_refresh(*_args, **_kwargs):
        raise AssertionError("Norges Bank network fetch should be avoided")

    monkeypatch.setattr(fx_freshness, "refresh_norges_bank_fx", unexpected_refresh)
    result = asyncio.run(
        fx_freshness.repair_norges_bank_fx_if_stale(
            repository,
            now=datetime(2026, 8, 21, 6, 0, tzinfo=UTC),
        )
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "fx_current"
    assert result["network_fetches_avoided"] is True


def test_fast_fx_repair_fetches_only_short_window_when_stale(monkeypatch) -> None:
    repository = FakeRepository(brl_date="2026-08-19", usd_date="2026-08-19")
    calls: dict[str, Any] = {}

    async def fake_refresh(repo, *, target_date, lookback_days, archive_bucket=None):
        calls.update(
            target_date=target_date,
            lookback_days=lookback_days,
            archive_bucket=archive_bucket,
        )
        repo.fx["BRL"] = target_date
        repo.fx["USD"] = target_date
        return {"status": "ok", "rows_written": 4}

    monkeypatch.setattr(fx_freshness, "refresh_norges_bank_fx", fake_refresh)
    result = asyncio.run(
        fx_freshness.repair_norges_bank_fx_if_stale(
            repository,
            now=datetime(2026, 8, 21, 6, 0, tzinfo=UTC),
            archive_bucket="R2",
        )
    )
    assert calls == {
        "target_date": "2026-08-20",
        "lookback_days": 7,
        "archive_bucket": "R2",
    }
    assert result["status"] == "ok"
    assert result["repaired"] is True
    assert result["latest_common_date"] == "2026-08-20"


def test_runtime_status_reports_current_fx_and_jobs() -> None:
    repository = FakeRepository(brl_date="2026-08-20", usd_date="2026-08-20")
    result = asyncio.run(
        runtime_status_summary(
            repository,
            now=datetime(2026, 8, 21, 6, 0, tzinfo=UTC),
        )
    )
    assert result["ready"] is True
    assert result["status"] == "OK"
    assert result["full_refresh"]["status"] == "SUCCESS"
    assert result["fast_refresh"]["status"] == "SUCCESS"
    assert result["norges_bank"]["status"] == "OK"
    assert result["fx"]["latest_common_date"] == "2026-08-20"
    assert result["fx"]["expected_date"] == "2026-08-20"
    assert result["fx"]["current"] is True


def test_runtime_status_flags_stale_fx() -> None:
    repository = FakeRepository(brl_date="2026-08-19", usd_date="2026-08-19")
    result = asyncio.run(
        runtime_status_summary(
            repository,
            now=datetime(2026, 8, 21, 6, 0, tzinfo=UTC),
        )
    )
    assert result["ready"] is True
    assert result["status"] == "DEGRADED"
    assert result["fx"]["current"] is False


def test_runtime_status_is_wired_to_api_frontend_and_fast_refresh() -> None:
    app = (ROOT / "cloudflare" / "src" / "app.py").read_text(encoding="utf-8")
    scheduled = (ROOT / "cloudflare" / "src" / "scheduled.py").read_text(encoding="utf-8")
    main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "frontend" / "src" / "RuntimeStatusPanel.tsx").read_text(encoding="utf-8")
    polling = (ROOT / "frontend" / "src" / "usePollingResource.ts").read_text(encoding="utf-8")

    assert '@app.get("/api/dashboard/runtime-status")' in app
    assert "repair_norges_bank_fx_if_stale" in scheduled
    assert scheduled.index("norges_bank_fx_repair") < scheduled.index('"dirty_nav"')
    assert "<RuntimeStatusMount />" in main
    assert '"/api/dashboard/runtime-status"' in panel
    assert "usePollingResource<RuntimeStatus>" in panel
    assert "fetch(url" in polling
