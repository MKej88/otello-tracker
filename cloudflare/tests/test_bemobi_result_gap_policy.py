"""Regressions for Bemobi result gaps and actionable source diagnostics."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

import bemobi_web_refresh_runtime as runtime  # noqa: E402
from full_refresh import _source_group_detail  # noqa: E402


@pytest.mark.parametrize(
    ("reason", "has_last_good", "needs_attention"),
    [
        ("result_documents_not_parseable", True, False),
        ("result_documents_not_parseable", False, True),
        ("newer_result_documents_not_parseable", True, True),
        ("newer_result_documents_not_parseable", False, True),
    ],
)
def test_only_expected_result_gap_with_last_good_is_nonblocking(
    reason: str, has_last_good: bool, needs_attention: bool
) -> None:
    result = {"status": "not_available", "reason": reason}
    assert runtime._result_release_needs_attention(
        result, has_last_good=has_last_good
    ) is needs_attention


class StubRepository:
    def __init__(self, has_last_good: bool) -> None:
        self.has_last_good = has_last_good
        self.reads = 0

    async def first(self, sql, parameters=()):
        self.reads += 1
        assert "fact_type='RESULT'" in sql
        return {"found": 1} if self.has_last_good else None


def _simulate_refresh(monkeypatch, reason: str, has_last_good: bool):
    async def ir(*args, **kwargs):
        return {"status": "ok", "rows_written": 0}

    async def distribution(*args, **kwargs):
        return {"status": "ok", "rows_written": 0}

    async def release(*args, **kwargs):
        return {
            "status": "not_available",
            "reason": reason,
            "errors": ["Unparseable PDF"],
            "rows_written": 0,
        }

    async def q3(*args, **kwargs):
        return {"status": "skipped"}

    async def agenda(*args, **kwargs):
        return {"status": "ok", "rows_written": 0}

    monkeypatch.setattr(runtime, "_secondary_refresh_slot", lambda _day: "result_release")
    monkeypatch.setattr(runtime, "sync_bemobi_ir", ir)
    monkeypatch.setattr(runtime, "sync_confirmed_bemobi_distribution_cash", distribution)
    monkeypatch.setattr(runtime, "sync_latest_result_release", release)
    monkeypatch.setattr(runtime, "sync_q3_previews", q3)
    monkeypatch.setattr(runtime, "refresh_agenda", agenda)
    repository = StubRepository(has_last_good)
    return (
        asyncio.run(runtime.refresh_bemobi_web(repository, target_date="2026-10-27")),
        repository,
    )


def test_existing_official_result_prevents_false_bemobi_partial(monkeypatch) -> None:
    result, repository = _simulate_refresh(
        monkeypatch, "result_documents_not_parseable", True
    )
    assert repository.reads == 1
    assert result["status"] == "ok"
    assert result["result_release_expected_gap"] is True
    assert result["result_release"]["last_good_preserved"] is True
    assert result["secondary_status"] == "ok"
    assert not result["secondary_warnings"]


def test_newer_unparseable_result_still_degrades_bemobi(monkeypatch) -> None:
    result, repository = _simulate_refresh(
        monkeypatch, "newer_result_documents_not_parseable", True
    )
    assert repository.reads == 0
    assert result["status"] == "partial"
    assert result["result_release_expected_gap"] is False
    assert result["secondary_status"] == "degraded"


def test_missing_last_good_still_degrades_bemobi(monkeypatch) -> None:
    result, repository = _simulate_refresh(
        monkeypatch, "result_documents_not_parseable", False
    )
    assert repository.reads == 1
    assert result["status"] == "partial"


def test_bemobi_distribution_failure_explains_source_warning() -> None:
    sources = {
        "bemobi_web": {
            "status": "partial",
            "ir": {"status": "ok"},
            "distribution_cash": {
                "status": "error",
                "reason": "confirmed_distribution_cash_sync_failed",
                "error": "missing confirmed payout",
            },
        }
    }
    message = _source_group_detail(
        "BEMOBI_IR", sources, {"bemobi_web": "DEGRADED"}
    )
    assert "Bekreftede Bemobi-utdelinger" in message
    assert "missing confirmed payout" in message


def test_bemobi_newer_result_failure_explains_source_warning() -> None:
    sources = {
        "bemobi_web": {
            "status": "partial",
            "ir": {"status": "ok"},
            "result_release": {
                "status": "not_available",
                "reason": "newer_result_documents_not_parseable",
                "errors": ["new report parse failed"],
            },
        }
    }
    message = _source_group_detail(
        "BEMOBI_IR", sources, {"bemobi_web": "DEGRADED"}
    )
    assert "Bemobi resultatrapport" in message
    assert "new report parse failed" in message
