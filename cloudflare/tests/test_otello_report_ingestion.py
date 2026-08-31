from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

import otello_report_ingestion  # noqa: E402
from otello_report_ingestion import (  # noqa: E402
    _apply_report,
    _cleanup_report_anchors,
    _upsert_post_report_cash_events,
)


class Repository:
    def __init__(self) -> None:
        self.runs: list[tuple[str, tuple[Any, ...]]] = []

    async def first(self, _sql: str, _params: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": 41,
            "amount_original": "10",
            "currency": "USD",
            "amount_nok": "100",
            "fx_rate_to_nok": "10",
        }

    async def run(self, sql: str, params: tuple[Any, ...]) -> None:
        self.runs.append((sql, params))


class CleanupRepository:
    def __init__(self) -> None:
        self.batches: list[list[tuple[str, tuple[Any, ...]]]] = []
        self.runs: list[tuple[str, tuple[Any, ...]]] = []

    async def run_batch(
        self, statements: list[tuple[str, tuple[Any, ...]]]
    ) -> None:
        self.batches.append(statements)

    async def first(self, _sql: str, _params: tuple[Any, ...]) -> dict[str, str]:
        return {"metadata_json": "{}"}

    async def run(self, sql: str, params: tuple[Any, ...]) -> None:
        self.runs.append((sql, params))


def test_report_cleanup_deletes_related_financial_data_in_one_batch() -> None:
    repository = CleanupRepository()

    asyncio.run(_cleanup_report_anchors(repository, report_doc_id=7))

    assert len(repository.batches) == 1
    statements = repository.batches[0]
    assert len(statements) == 4
    assert all(params == (7,) for _sql, params in statements)
    assert "DELETE FROM cash_movements" in statements[0][0]
    assert "DELETE FROM other_net_assets_anchors" in statements[1][0]
    assert "DELETE FROM other_net_assets_reported_anchors" in statements[2][0]
    assert "DELETE FROM cash_anchors" in statements[3][0]
    assert len(repository.runs) == 1
    assert "UPDATE source_documents" in repository.runs[0][0]


def test_existing_cash_event_gets_corrected_fx_conversion() -> None:
    repository = Repository()
    events = [
        {
            "movement_date": "2026-08-28",
            "event_type": "DIVIDEND",
            "amount_usd": "10",
            "amount_nok": "120",
            "description": "Utbytte mottatt",
            "fx": {"rate": "12", "rate_date": "2026-08-28"},
        }
    ]

    result = asyncio.run(
        _upsert_post_report_cash_events(repository, report_doc_id=7, prepared_events=events)
    )

    assert result["events"][0]["status"] == "updated"
    assert result["events"][0]["amount_nok"] == "120"
    assert len(repository.runs) == 1
    sql, params = repository.runs[0]
    assert "UPDATE cash_movements" in sql
    assert params == ("120", "12", "Utbytte mottatt", 7, 41)


def test_unchanged_cash_event_is_not_written_again() -> None:
    repository = Repository()
    events = [
        {
            "movement_date": "2026-08-28",
            "event_type": "DIVIDEND",
            "amount_usd": "10",
            "amount_nok": "100",
            "description": "Utbytte mottatt",
            "fx": {"rate": "10", "rate_date": "2026-08-28"},
        }
    ]

    result = asyncio.run(
        _upsert_post_report_cash_events(repository, report_doc_id=7, prepared_events=events)
    )

    assert result["events"][0]["status"] == "existing"
    assert repository.runs == []


def test_apply_report_marks_partial_when_nav_rebuild_fails(monkeypatch) -> None:
    statuses: list[str] = []

    async def nearest_fx(*_args: Any) -> dict[str, str]:
        return {"rate": "10"}

    async def no_receivables(*_args: Any) -> int:
        return 0

    async def prepared_events(*_args: Any) -> list[dict[str, Any]]:
        return []

    async def anchor_id(*_args: Any) -> int:
        return 11

    async def ona_ids(*_args: Any) -> tuple[int, int]:
        return (12, 13)

    async def cash_events(*_args: Any) -> dict[str, Any]:
        return {"count": 0, "events": []}

    async def cost_ok(*_args: Any) -> dict[str, str]:
        return {"status": "ok"}

    async def nav_fails(*_args: Any) -> dict[str, Any]:
        raise RuntimeError("NAV kunne ikke bygges")

    async def record_status(_repository: Any, _document_id: int, status: str) -> None:
        statuses.append(status)

    monkeypatch.setattr(otello_report_ingestion, "_nearest_usd_nok", nearest_fx)
    monkeypatch.setattr(
        otello_report_ingestion,
        "_active_bemobi_receivable_count",
        no_receivables,
    )
    monkeypatch.setattr(
        otello_report_ingestion,
        "_prepare_post_report_cash_events",
        prepared_events,
    )
    monkeypatch.setattr(otello_report_ingestion, "_upsert_cash_anchor", anchor_id)
    monkeypatch.setattr(otello_report_ingestion, "_upsert_ona_anchor", ona_ids)
    monkeypatch.setattr(
        otello_report_ingestion,
        "_upsert_post_report_cash_events",
        cash_events,
    )
    monkeypatch.setattr(otello_report_ingestion, "_upsert_cost_anchors", cost_ok)
    monkeypatch.setattr(
        otello_report_ingestion,
        "_backfill_affected_nav",
        nav_fails,
    )
    monkeypatch.setattr(
        otello_report_ingestion,
        "_set_report_document_apply_status",
        record_status,
    )

    result = asyncio.run(
        _apply_report(
            object(),
            report_doc_id=7,
            facts={"report_date": "2026-08-29"},
            target_date="2026-08-30",
        )
    )

    assert result["status"] == "partial"
    assert result["nav_backfill"]["status"] == "error"
    assert result["warnings"] == [
        {"step": "nav_backfill", "error": "NAV kunne ikke bygges"}
    ]
    assert statuses == ["APPLIED", "PARTIAL"]
