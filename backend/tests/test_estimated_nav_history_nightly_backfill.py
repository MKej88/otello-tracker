from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FULL_REFRESH = ROOT / "cloudflare" / "src" / "full_refresh.py"
ENTRY = ROOT / "cloudflare" / "src" / "entry.py"
MATERIALIZER = ROOT / "cloudflare" / "src" / "estimated_nav_history_materialization.py"
CLOUDFLARE_RETRY_MIGRATION = (
    ROOT / "cloudflare" / "migrations" / "0032_estimated_nav_history_retry_queue.sql"
)
BACKEND_RETRY_MIGRATION = (
    ROOT / "backend" / "app" / "db" / "migrations" / "0035_estimated_nav_history_retry_queue.sql"
)


def test_nightly_history_backfill_uses_separate_durable_workflow_steps() -> None:
    full_refresh = FULL_REFRESH.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    materializer = MATERIALIZER.read_text(encoding="utf-8")

    assert "HISTORY_MATERIALIZATION_BATCH_SIZE = 50" in full_refresh
    assert "MAX_HISTORY_MATERIALIZATION_BATCHES = 24" in full_refresh
    assert "async def materialize_history_batch(" in full_refresh
    assert "after_date: str | None = None" in full_refresh
    assert "def summarize_history_materialization(batches" in full_refresh
    assert 'stop_reason = "complete" if not last_failures else "complete_with_skips"' in full_refresh
    assert 'stop_reason = "no_progress"' in full_refresh
    assert 'stop_reason = "batch_limit"' in full_refresh
    assert 'stop_reason = "continue"' in full_refresh
    assert '"next_cursor": last.get("next_cursor")' in full_refresh

    assert "_materialize_history_until_guard" not in full_refresh
    finish_source = full_refresh.split("async def finish_full_refresh", 1)[1]
    assert "for batch_number in range" not in finish_source
    assert "estimated_nav_history_result is not None" in finish_source

    assert "after_date: str | None = None" in materializer
    assert "SCAN_CURSOR_STATE_KEY" in materializer
    assert "SELECT value FROM runtime_state WHERE key=? LIMIT 1" in materializer
    assert "INSERT INTO runtime_state(key, value, updated_at)" in materializer
    assert "persistent_cursor = await _load_scan_cursor(repository)" in materializer
    assert "effective_after_date = max(" in materializer
    assert "substr(n.as_of_at, 1, 10) > ?" in materializer
    assert 'next_cursor = str(rows[-1]["date"]) if rows else effective_after_date' in materializer
    assert "persisted_cursor_after = await _save_scan_cursor(repository, next_cursor)" in materializer
    assert '"attempted": attempted' in materializer
    assert '"cursor_advanced": bool(rows) and next_cursor != effective_after_date' in materializer

    assert "estimated_nav_history_retry_queue" in materializer
    assert "RETRY_BATCH_SIZE = 10" in materializer
    assert "RETRY_DELAY_DAYS = 7" in materializer
    assert "async def _retry_due_failures(" in materializer
    assert "strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)" in materializer
    assert "attempts=attempts + 1" in materializer
    assert "if attempted < batch_size" in materializer

    assert "for batch_number in range(1, MAX_HISTORY_MATERIALIZATION_BATCHES + 1):" in entry
    assert "history_cursor: str | None = None" in entry
    assert "batch_after_date = history_cursor" in entry
    assert 'f"materialize estimated NAV history {batch_number}"' in entry
    assert '"timeout": "10 minutes"' in entry
    assert "after_date=batch_after_date" in entry
    assert 'history_cursor = history_batch.get("next_cursor") or history_cursor' in entry
    assert 'await renew_lock(f"after estimated NAV history {batch_number}")' in entry
    assert 'estimated_nav_history.get("stop_reason") != "continue"' in entry
    assert "estimated_nav_history_result=estimated_nav_history" in entry


def test_nav_history_retry_queue_is_present_in_both_schemas() -> None:
    cloudflare = CLOUDFLARE_RETRY_MIGRATION.read_text(encoding="utf-8")
    backend = BACKEND_RETRY_MIGRATION.read_text(encoding="utf-8")

    assert cloudflare == backend
    assert "CREATE TABLE estimated_nav_history_retry_queue" in cloudflare
    assert "PRIMARY KEY (date, calculation_version)" in cloudflare
    assert "CHECK (attempts > 0)" in cloudflare
    assert "idx_estimated_nav_history_retry_due" in cloudflare
    assert "calculation_version, next_retry_at, date" in cloudflare


def test_history_summary_retains_bounded_phase_timings_and_cache_status() -> None:
    import sys
    sys.path.insert(0, str(ROOT / "cloudflare" / "src"))
    from full_refresh import summarize_history_materialization

    first = {"written": 50, "attempted": 50, "cursor_advanced": True,
             "timings_ms": {"scan_ms": 10.5}, "failures": []}
    last = {"written": 1, "attempted": 1, "cursor_advanced": True,
            "timings_ms": {"scan_ms": 2.5, "retry_ms": 3, "period_cache_ms": 8},
            "retry": {"attempted": 0, "pending": 0},
            "period_cache": {"status": "ok", "timings_ms": {"1m": 1.5}},
            "failures": []}
    summary = summarize_history_materialization([first, last])
    assert summary["complete"]
    assert summary["written"] == 51
    assert summary["timings_ms"] == {"scan_ms": 13.0, "retry_ms": 3.0, "period_cache_ms": 8.0}
    assert summary["period_cache"]["status"] == "ok"
    assert summary["retry"]["pending"] == 0


def test_workflow_defers_cache_to_independent_period_steps() -> None:
    entry = ENTRY.read_text(encoding="utf-8")
    assert "build_period_cache=False" in entry
    assert 'if estimated_nav_history.get("complete"):' in entry
    assert "for period_key in PERIOD_KEYS:" in entry
    assert 'f"materialize NAV period {period_key}"' in entry
    assert 'await renew_lock(f"after NAV period {period_key}")' in entry


def test_period_summary_rejects_missing_failed_and_mixed_date_steps() -> None:
    import sys
    sys.path.insert(0, str(ROOT / "cloudflare" / "src"))
    from full_refresh import summarize_history_periods
    from materialized_discount_history import PERIOD_KEYS, PERIOD_CACHE_VERSION

    results = {key: {"status": "ok", "periods": [key], "written": 1,
                     "source_date": "2026-11-25", "calculation_version": PERIOD_CACHE_VERSION,
                     "timings_ms": {key: 2}, "repository": {"d1_reads": 10}}
               for key in PERIOD_KEYS}
    ready = summarize_history_periods(results)
    assert ready["status"] == "ok" and ready["written"] == 6
    assert ready["repository_by_period"]["1y"]["d1_reads"] == 10
    assert ready["timings_ms"]["1y"] == 2
    assert summarize_history_periods({**results, "1y": {"status": "error", "error": "memory limit"}})["status"] == "partial"
    assert summarize_history_periods({key: value for key, value in results.items() if key != "1y"})["written"] == 5
    mixed = {**results, "1y": {**results["1y"], "source_date": "2026-11-24"}}
    assert summarize_history_periods(mixed)["status"] == "partial"


def test_single_period_uses_same_calculation_and_cache_write(monkeypatch) -> None:
    import asyncio
    import sys
    sys.path.insert(0, str(ROOT / "cloudflare" / "src"))
    import materialized_discount_history as cache

    calls = []
    writes = []

    async def latest(repository):
        return "2026-11-25"

    async def history(repository, **kwargs):
        calls.append(kwargs)
        return {"estimated": {"ready": True, "to": "2026-11-25", "marker": kwargs["days"]}}

    async def enrich(repository, payload):
        return payload

    async def write(repository, **kwargs):
        writes.append(kwargs)

    monkeypatch.setattr(cache, "_latest_history_date", latest)
    monkeypatch.setattr(cache, "discount_history", history)
    monkeypatch.setattr(cache, "_enrich_life360_period", enrich)
    monkeypatch.setattr(cache, "_write_entry", write)
    whole = asyncio.run(cache.materialize_discount_periods(object()))
    original = list(writes)
    writes.clear()
    calls.clear()
    for key in cache.PERIOD_KEYS:
        result = asyncio.run(cache.materialize_discount_periods(object(), period_keys=(key,)))
        assert result["status"] == "ok" and result["periods"] == [key]
    assert whole["written"] == 6
    assert writes == original
