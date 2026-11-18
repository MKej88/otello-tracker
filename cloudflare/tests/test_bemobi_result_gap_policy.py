"""Regressions for Bemobi result gaps and actionable source diagnostics."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

import bemobi_web_refresh_runtime as runtime  # noqa: E402
from full_refresh import _source_group_detail, _degraded_source_blocks_job, merge_bemobi_ir_news_health  # noqa: E402


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
    monkeypatch.setattr(runtime, "refresh_official_distributions", distribution)
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


def test_optional_report_feed_failure_is_nonblocking_after_verified_new_release() -> None:
    release = {"status": "ok", "period": "3Q26", "rows_written": 3}
    result = merge_bemobi_ir_news_health(
        {"status": "ok", "result_release": release, "best_effort_warnings": []},
        {"status": "ok", "report_feed_status": "partial", "report_feed_errors": ["HTTP 503"]},
    )
    assert result["status"] == "partial"
    assert result["non_blocking_degraded"] is True
    assert not _degraded_source_blocks_job("BEMOBI_IR", {"bemobi_web": result})
    assert result["result_release"] == release
    assert result["report_feed_warning_non_blocking"] is True
    assert result["best_effort_status"] == "degraded"
    assert result["best_effort_warnings"][0]["errors"] == ["HTTP 503"]


def test_optional_report_feed_failure_still_degrades_without_new_verified_release() -> None:
    result = merge_bemobi_ir_news_health(
        {"status": "ok", "result_release": {"status": "skipped", "reason": "latest_result_already_ingested"}},
        {"status": "ok", "report_feed_status": "partial", "report_feed_errors": ["HTTP 503"]},
    )
    assert result["status"] == "partial"
    detail = _source_group_detail(
        "BEMOBI_IR", {"bemobi_web": result}, {"bemobi_web": "DEGRADED"}
    )
    assert "dokumentfeed" in detail
    assert "HTTP 503" in detail


def test_mandatory_ir_notices_failure_still_degrades_even_with_valid_release() -> None:
    result = merge_bemobi_ir_news_health(
        {"status": "ok", "result_release": {"status": "ok", "period": "3Q26"}},
        {"status": "not_available", "error": "HTTP 429", "last_good_preserved": True},
    )
    assert result["status"] == "partial"
    assert not result.get("report_feed_warning_non_blocking")
    detail = _source_group_detail(
        "BEMOBI_IR", {"bemobi_web": result}, {"bemobi_web": "DEGRADED"}
    )
    assert "HTTP 429" in detail


def test_newer_unparseable_release_takes_precedence_over_optional_feed_detail() -> None:
    result = merge_bemobi_ir_news_health(
        {
            "status": "partial",
            "ir": {"status": "ok"},
            "result_release": {
                "status": "not_available",
                "reason": "newer_result_documents_not_parseable",
                "errors": ["bad Q3 PDF"],
            },
        },
        {"status": "ok", "report_feed_status": "partial", "report_feed_errors": ["HTTP 503"]},
    )
    assert result["status"] == "partial"
    detail = _source_group_detail(
        "BEMOBI_IR", {"bemobi_web": result}, {"bemobi_web": "DEGRADED"}
    )
    assert "bad Q3 PDF" in detail
    assert "Bemobi resultatrapport" in detail


def test_newsweb_review_health_includes_only_public_message_ids_and_reasons():
    from full_refresh import _source_group_detail

    result = _source_group_detail(
        "NEWSWEB",
        {"otello_reports": {
            "status": "review_required", "review_required": 2,
            "review_messages": [
                {"message_id": 686525, "reason": "attachment_not_validated"},
                {"message_id": 680445, "reason": "invalid_pdf"},
            ],
        }},
        {"otello_reports": "DOWN"},
    )
    assert result is not None
    assert "686525:attachment_not_validated" in result
    assert "680445:invalid_pdf" in result


def test_bemobi_empty_feed_source_status_shows_probe_counts():
    detail = _source_group_detail(
        "BEMOBI_IR",
        {"bemobi_web": {
            "status": "partial",
            "ir_news": {
                "status": "ok", "report_feed_status": "empty",
                "report_feed_probes": [
                    {"year": 2026, "scope": "all", "release_count": 0},
                    {"year": 2026, "scope": "earnings", "release_count": 0},
                ],
            },
        }},
        {"bemobi_web": "DEGRADED"},
    )
    assert detail is not None
    assert "2026:all=0 utgivelser" in detail
    assert "2026:earnings=0 utgivelser" in detail

