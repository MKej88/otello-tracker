from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_ROOT = ROOT / "cloudflare"
CLOUDFLARE_SRC = CLOUDFLARE_ROOT / "src"
for path in (CLOUDFLARE_ROOT, CLOUDFLARE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import bemobi_web_refresh_runtime as runtime  # noqa: E402
import bemobi_web_refresh_v2 as legacy_v2  # noqa: E402
from src import full_refresh as full_refresh_runtime  # noqa: E402


def test_v2_import_path_is_only_a_runtime_compatibility_shim() -> None:
    assert legacy_v2.refresh_bemobi_web is runtime.refresh_bemobi_web
    assert legacy_v2._ensure_consensus_event is runtime._ensure_consensus_event
    assert not hasattr(legacy_v2, "sync_marketscreener_consensus")
    assert not hasattr(legacy_v2, "parse_forward_consensus_html")


def test_active_runtime_has_no_aggregator_dependency() -> None:
    source = (CLOUDFLARE_SRC / "bemobi_web_refresh_runtime.py").read_text(encoding="utf-8")
    assert "marketscreener" not in source.lower()
    assert "MARKETSCREENER_FINANCES_URL" not in source
    assert "sync_marketscreener_consensus" not in source


def test_heavy_secondary_web_sources_alternate_nights() -> None:
    slots = {runtime._secondary_refresh_slot(day) for day in ("2026-08-21", "2026-08-22")}
    assert slots == {"result_release", "xp_preview"}
    assert len(runtime._SECONDARY_REFRESH_SLOTS) == 2


def test_scheduled_secondary_skip_is_not_a_source_failure() -> None:
    skipped = runtime._scheduled_skip("xp_preview", "result_release")
    assert skipped == {
        "status": "skipped",
        "reason": "rotating_cpu_budget",
        "slot": "xp_preview",
        "active_slot": "result_release",
        "rows_written": 0,
    }


def test_broker_models_are_source_specific_and_not_scraped_nightly(monkeypatch) -> None:
    async def ok_ir(*args, **kwargs):
        return {"status": "ok", "rows_written": 5}

    async def no_result(*args, **kwargs):
        return {"status": "skipped", "rows_written": 0}

    async def no_event(*args, **kwargs):
        return 0

    monkeypatch.setattr(runtime, "sync_bemobi_ir", ok_ir)
    monkeypatch.setattr(runtime, "sync_latest_result_release", no_result)
    monkeypatch.setattr(runtime, "_ensure_consensus_event", no_event)
    monkeypatch.setattr(runtime, "_secondary_refresh_slot", lambda _day: "result_release")

    result = asyncio.run(runtime.refresh_bemobi_web(object(), target_date="2026-08-29"))

    assert result["status"] == "ok"
    assert result["rows_written"] == 5
    assert result["consensus"] == {
        "status": "skipped",
        "reason": "source_specific_public_broker_models",
        "rows_written": 0,
    }
    assert result["broker_models"] == result["consensus"]
    assert result["secondary_status"] == "ok"
    assert result["secondary_warnings"] == []


def test_transient_official_ir_failure_preserves_last_good_without_blocking_nightly(monkeypatch) -> None:
    failed_url = runtime.BEMOBI_OWNERSHIP_URL

    async def failed_ir(*args, **kwargs):
        raise RuntimeError(f"Bemobi IR fetch feilet for {failed_url}: HTTP 503")

    async def no_xp(*args, **kwargs):
        return {"status": "skipped", "rows_written": 0}

    monkeypatch.setattr(runtime, "sync_bemobi_ir", failed_ir)
    monkeypatch.setattr(runtime, "sync_xp_preview", no_xp)
    monkeypatch.setattr(runtime, "_secondary_refresh_slot", lambda _day: "xp_preview")

    result = asyncio.run(runtime.refresh_bemobi_web(object(), target_date="2026-08-28"))
    assert result["status"] == "partial"
    assert result["non_blocking_degraded"] is True
    assert result["ir"]["status"] == "not_available"
    assert result["ir"]["last_good_preserved"] is True
    assert result["ir"]["failed_url"] == failed_url
    assert full_refresh_runtime._source_health_status(result) == "DEGRADED"
    assert full_refresh_runtime._degraded_source_blocks_job(
        "BEMOBI_IR", {"bemobi_web": result}
    ) is False


def test_ir_parser_failure_resolves_source_url() -> None:
    exc = ValueError("Bemobi IR analytikertabell ga for få gyldige rader")
    assert runtime._ir_failed_url(exc) == runtime.BEMOBI_ANALYST_URL


def test_unparseable_official_result_still_degrades_bemobi_ir(monkeypatch) -> None:
    async def ok_ir(*args, **kwargs):
        return {"status": "ok", "rows_written": 5}

    async def bad_result(*args, **kwargs):
        return {"status": "not_available", "error": "new result not parseable", "rows_written": 0}

    async def no_event(*args, **kwargs):
        return 0

    monkeypatch.setattr(runtime, "sync_bemobi_ir", ok_ir)
    monkeypatch.setattr(runtime, "sync_latest_result_release", bad_result)
    monkeypatch.setattr(runtime, "_ensure_consensus_event", no_event)
    monkeypatch.setattr(runtime, "_secondary_refresh_slot", lambda _day: "result_release")

    result = asyncio.run(runtime.refresh_bemobi_web(object(), target_date="2026-08-26"))
    assert result["status"] == "partial"
    assert result["non_blocking_degraded"] is False
    assert result["secondary_status"] == "degraded"
    assert result["secondary_warnings"][0]["source"] == "result_release"
    assert full_refresh_runtime._degraded_source_blocks_job(
        "BEMOBI_IR", {"bemobi_web": result}
    ) is True
