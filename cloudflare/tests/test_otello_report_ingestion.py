from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from otello_report_ingestion import _upsert_post_report_cash_events  # noqa: E402


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
