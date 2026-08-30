from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import bemobi_cvm_post_result as post_result  # noqa: E402


class _Repository:
    def __init__(self, *, quarter_exists: bool = True) -> None:
        self.quarter_exists = quarter_exists
        self.runs: list[tuple[str, tuple]] = []

    async def first(self, sql: str, params=()):
        assert "fact_type='TTM_QUARTER'" in sql
        assert params == ("3Q26",)
        return {"id": 123} if self.quarter_exists else None

    async def run(self, sql: str, params=()):
        self.runs.append((sql, tuple(params)))
        return None


def test_post_result_refresh_invalidates_same_day_throttle_before_cvm_retry(monkeypatch) -> None:
    repository = _Repository()
    calls = []
    harmonized_calls = []

    async def fake_harmonized(repo, *, period: str):
        harmonized_calls.append((repo, period))
        return {"status": "updated", "rows_written": 1, "value_mbrl": 240.0}

    async def fake_refresh(repo, *, target_date: str, fetcher=None):
        calls.append((repo, target_date, fetcher))
        assert repository.runs == [
            (
                "DELETE FROM runtime_state WHERE key=?",
                (post_result._LAST_ATTEMPT_KEY,),
            )
        ]
        return {
            "status": "ok",
            "rows_written": 1,
            "fact_status": {"3Q26": "updated"},
        }

    monkeypatch.setattr(post_result, "_merge_harmonized_revenue_from_result", fake_harmonized)
    monkeypatch.setattr(post_result, "refresh_bemobi_reported_net_income", fake_refresh)

    result = asyncio.run(
        post_result.refresh_cvm_financials_after_new_result(
            repository,
            target_date="2026-11-10",
            period="3Q26",
        )
    )

    assert harmonized_calls == [(repository, "3Q26")]
    assert len(calls) == 1
    assert result["status"] == "ok"
    assert result["rows_written"] == 2
    assert result["trigger"] == "new_result_release"
    assert result["trigger_period"] == "3Q26"
    assert result["trigger_period_status"] == "updated"
    assert result["harmonized_revenue"]["status"] == "updated"
    assert result["retry_throttle_reset"] is True


def test_post_result_refresh_does_not_reset_throttle_without_new_quarter(monkeypatch) -> None:
    repository = _Repository(quarter_exists=False)

    async def unexpected_refresh(*args, **kwargs):
        raise AssertionError("CVM refresh should not run without the new TTM quarter")

    async def unexpected_harmonized(*args, **kwargs):
        raise AssertionError("Harmonized revenue should not run without the new TTM quarter")

    monkeypatch.setattr(post_result, "refresh_bemobi_reported_net_income", unexpected_refresh)
    monkeypatch.setattr(post_result, "_merge_harmonized_revenue_from_result", unexpected_harmonized)

    result = asyncio.run(
        post_result.refresh_cvm_financials_after_new_result(
            repository,
            target_date="2026-11-10",
            period="3Q26",
        )
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "new_result_quarter_fact_missing"
    assert result["retry_throttle_reset"] is False
    assert repository.runs == []


def test_bemobi_runtime_rechecks_cvm_after_new_result_release() -> None:
    runtime = (ROOT / "cloudflare/src/bemobi_web_refresh_runtime.py").read_text(encoding="utf-8")

    result_ingest = runtime.index("result = await sync_latest_result_release")
    post_result_retry = runtime.index("post_result_cvm = await refresh_cvm_financials_after_new_result")

    assert result_ingest < post_result_retry
    assert 'if result.get("status") == "ok" and result.get("period")' in runtime
    assert '"post_result_cvm_financials": post_result_cvm' in runtime
    assert '"reason": "custom_web_fetcher"' in runtime
