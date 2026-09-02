from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FULL_REFRESH = ROOT / "cloudflare" / "src" / "full_refresh.py"


def test_nightly_history_backfill_runs_multiple_restart_safe_batches() -> None:
    source = FULL_REFRESH.read_text(encoding="utf-8")

    assert "_HISTORY_MATERIALIZATION_BATCH_SIZE = 100" in source
    assert "_MAX_HISTORY_MATERIALIZATION_BATCHES = 12" in source
    assert "async def _materialize_history_until_guard(repository)" in source
    assert "for batch_number in range(1, _MAX_HISTORY_MATERIALIZATION_BATCHES + 1):" in source
    assert "if attempted < _HISTORY_MATERIALIZATION_BATCH_SIZE:" in source
    assert '"stop_reason": "complete" if complete else "blocked_by_failures"' in source
    assert "if written == 0:" in source
    assert '"stop_reason": "no_progress"' in source
    assert '"stop_reason": "batch_limit"' in source
    assert "estimated_nav_history = await _materialize_history_until_guard(repository)" in source
