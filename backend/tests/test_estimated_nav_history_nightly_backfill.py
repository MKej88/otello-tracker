from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FULL_REFRESH = ROOT / "cloudflare" / "src" / "full_refresh.py"
ENTRY = ROOT / "cloudflare" / "src" / "entry.py"
MATERIALIZER = ROOT / "cloudflare" / "src" / "estimated_nav_history_materialization.py"


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
    assert "substr(n.as_of_at, 1, 10) > ?" in materializer
    assert 'next_cursor = str(rows[-1]["date"]) if rows else after_date' in materializer
    assert '"attempted": attempted' in materializer
    assert '"cursor_advanced": bool(rows) and next_cursor != after_date' in materializer

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
