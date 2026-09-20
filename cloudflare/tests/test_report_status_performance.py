from __future__ import annotations

import asyncio

import pytest

from src import report_status


REPORT = {
    "id": 1,
    "title": "Halvårsrapport",
    "url": "https://example.test/report.pdf",
    "published_at": "2026-08-20T07:00:00Z",
    "metadata_json": (
        '{"message_id": 7, "facts": {"report_date": "2026-06-30"}}'
    ),
}


def test_independent_report_status_reads_run_concurrently(monkeypatch) -> None:
    started: list[str] = []
    all_started = asyncio.Event()

    async def read(name: str, result):
        started.append(name)
        if len(started) == 6:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=0.5)
        return result

    async def latest_report(_repository):
        return REPORT

    async def latest_news(_repository):
        return None

    monkeypatch.setattr(report_status, "_latest_report_document", latest_report)
    monkeypatch.setattr(report_status, "_latest_result_news", latest_news)
    monkeypatch.setattr(
        report_status,
        "_news_for_message",
        lambda *_args: read("news", None),
    )
    monkeypatch.setattr(
        report_status,
        "_previous_cash_anchor",
        lambda *_args: read("cash", None),
    )
    monkeypatch.setattr(
        report_status,
        "_previous_ona_anchor",
        lambda *_args: read("ona", None),
    )
    monkeypatch.setattr(
        report_status,
        "_latest_cost_anchor",
        lambda *_args, before: read(f"cost:{before}", None),
    )
    monkeypatch.setattr(
        report_status,
        "_report_nav_state",
        lambda *_args: read("nav", None),
    )

    result = asyncio.run(report_status.report_status_summary(object()))

    assert set(started) == {"news", "cash", "ona", "cost:False", "cost:True", "nav"}
    assert result["ready"] is True
    assert result["report_date"] == "2026-06-30"


def test_report_status_still_propagates_read_errors(monkeypatch) -> None:
    async def latest_report(_repository):
        return REPORT

    async def latest_news(_repository):
        return None

    async def fail(*_args, **_kwargs):
        raise RuntimeError("simulert databasefeil")

    async def empty(*_args, **_kwargs):
        return None

    monkeypatch.setattr(report_status, "_latest_report_document", latest_report)
    monkeypatch.setattr(report_status, "_latest_result_news", latest_news)
    monkeypatch.setattr(report_status, "_news_for_message", empty)
    monkeypatch.setattr(report_status, "_previous_cash_anchor", fail)
    monkeypatch.setattr(report_status, "_previous_ona_anchor", empty)
    monkeypatch.setattr(report_status, "_latest_cost_anchor", empty)
    monkeypatch.setattr(report_status, "_report_nav_state", empty)

    with pytest.raises(RuntimeError, match="simulert databasefeil"):
        asyncio.run(report_status.report_status_summary(object()))
