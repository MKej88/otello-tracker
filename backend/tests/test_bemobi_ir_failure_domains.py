from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_ROOT = ROOT / "cloudflare"
CLOUDFLARE_SRC = CLOUDFLARE_ROOT / "src"
for path in (CLOUDFLARE_ROOT, CLOUDFLARE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import bemobi_ir_refresh as ir_refresh  # noqa: E402
import bemobi_web_refresh_runtime as runtime  # noqa: E402
from src import full_refresh as full_refresh_runtime  # noqa: E402


def test_analyst_failure_does_not_fail_successful_ownership_refresh(monkeypatch) -> None:
    async def ok_ownership(*args, **kwargs):
        return {
            "status": "ok",
            "ownership": {"shares": 32_719_588, "ownership_pct": 38.22},
            "holding_changes": 0,
            "rows_written": 1,
        }

    async def failed_analysts(*args, **kwargs):
        raise ValueError("Bemobi IR analytikertabell ga for få gyldige rader")

    monkeypatch.setattr(ir_refresh, "sync_bemobi_ownership", ok_ownership)
    monkeypatch.setattr(ir_refresh, "sync_bemobi_analyst_coverage", failed_analysts)

    result = asyncio.run(
        ir_refresh.sync_bemobi_ir(object(), target_date="2026-08-29")
    )

    assert result["status"] == "ok"
    assert result["ownership_refresh"]["status"] == "ok"
    assert result["analyst_coverage"]["status"] == "not_available"
    assert result["analyst_coverage"]["reason"] == "analyst_coverage_refresh_failed"
    assert result["analyst_coverage"]["failed_url"] == ir_refresh.BEMOBI_ANALYST_URL
    assert result["analyst_coverage"]["last_good_preserved"] is True
    assert result["rows_written"] == 1
    assert "analyst_keys" not in result


def test_ownership_failure_still_escapes_core_ir_refresh(monkeypatch) -> None:
    analyst_called = False

    async def failed_ownership(*args, **kwargs):
        raise RuntimeError("ownership unavailable")

    async def analysts_must_not_run(*args, **kwargs):
        nonlocal analyst_called
        analyst_called = True
        return {"status": "ok", "rows_written": 0}

    monkeypatch.setattr(ir_refresh, "sync_bemobi_ownership", failed_ownership)
    monkeypatch.setattr(ir_refresh, "sync_bemobi_analyst_coverage", analysts_must_not_run)

    try:
        asyncio.run(ir_refresh.sync_bemobi_ir(object(), target_date="2026-08-29"))
    except RuntimeError as exc:
        assert "ownership unavailable" in str(exc)
    else:
        raise AssertionError("Ownership-feil skal fortsatt behandles som core IR-feil")

    assert analyst_called is False


class _HealthRepository:
    def __init__(self, analyst_payload: dict) -> None:
        self.analyst_payload = analyst_payload

    async def first(self, sql: str, parameters=()):
        assert "FROM source_health" in sql
        return {
            "metadata_json": json.dumps(
                {"result": {"ir": {"analyst_coverage": self.analyst_payload}}}
            )
        }


def test_prune_guard_ignores_failed_analyst_observation() -> None:
    repository = _HealthRepository(
        {
            "status": "not_available",
            "analyst_keys": ["BTG Pactual"],
        }
    )
    keys = asyncio.run(ir_refresh._previous_ir_analyst_keys(repository))
    assert keys is None


def test_prune_guard_reads_successful_nested_analyst_observation() -> None:
    repository = _HealthRepository(
        {
            "status": "ok",
            "analyst_keys": ["BTG Pactual", "XP"],
        }
    )
    keys = asyncio.run(ir_refresh._previous_ir_analyst_keys(repository))
    assert keys == {"BTG Pactual", "XP"}


def test_runtime_reports_analyst_failure_without_degrading_bemobi_source(monkeypatch) -> None:
    async def ir_with_analyst_warning(*args, **kwargs):
        return {
            "status": "ok",
            "ownership_refresh": {"status": "ok", "rows_written": 1},
            "analyst_coverage": {
                "status": "not_available",
                "reason": "analyst_coverage_refresh_failed",
                "error": "HTTP 503",
                "failed_url": runtime.BEMOBI_ANALYST_URL,
                "last_good_preserved": True,
                "rows_written": 0,
            },
            "rows_written": 1,
        }

    async def ok_consensus(*args, **kwargs):
        return {"status": "ok", "rows_written": 2}

    async def no_xp(*args, **kwargs):
        return {"status": "skipped", "rows_written": 0}

    monkeypatch.setattr(runtime, "sync_bemobi_ir", ir_with_analyst_warning)
    monkeypatch.setattr(runtime, "sync_marketscreener_consensus", ok_consensus)
    monkeypatch.setattr(runtime, "sync_xp_preview", no_xp)
    monkeypatch.setattr(runtime, "_secondary_refresh_slot", lambda _day: "xp_preview")

    result = asyncio.run(runtime.refresh_bemobi_web(object(), target_date="2026-08-29"))

    assert result["status"] == "ok"
    assert result["rows_written"] == 3
    assert result["best_effort_status"] == "degraded"
    assert result["best_effort_warnings"] == [
        {
            "source": "analyst_coverage",
            "status": "not_available",
            "reason": "analyst_coverage_refresh_failed",
            "error": "HTTP 503",
            "failed_url": runtime.BEMOBI_ANALYST_URL,
        }
    ]
    assert result["non_blocking_degraded"] is False
    assert full_refresh_runtime._source_health_status(result) == "OK"
