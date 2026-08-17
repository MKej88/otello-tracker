from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import newsweb_fast_refresh as nw_fast  # noqa: E402
from newsweb_client import NewsWebMessage  # noqa: E402
from performance_repository import PerformanceD1WriteRepository  # noqa: E402
from scheduled import _otec_refresh_plan  # noqa: E402


class _FakeResult:
    def __init__(self, results):
        self.results = results


class _FakeStatement:
    def __init__(self, database, sql):
        self.database = database
        self.sql = sql
        self.parameters = ()

    def bind(self, *parameters):
        self.parameters = parameters
        return self

    async def all(self):
        self.database.read_calls.append((self.sql, self.parameters))
        if "FROM sources" in self.sql:
            return _FakeResult([{"id": 7}])
        if "FROM instruments" in self.sql:
            return _FakeResult([{"id": 11}])
        return _FakeResult([{"value": 1}])

    async def run(self):
        self.database.write_calls.append((self.sql, self.parameters))
        return SimpleNamespace(success=True)


class _FakeD1:
    def __init__(self):
        self.read_calls = []
        self.write_calls = []

    def prepare(self, sql):
        return _FakeStatement(self, sql)


def test_performance_repository_caches_exact_reads_and_reference_ids() -> None:
    database = _FakeD1()
    repository = PerformanceD1WriteRepository(database)

    async def run():
        assert await repository.source_id("NEWSWEB") == 7
        assert await repository.source_id("NEWSWEB") == 7
        assert await repository.instrument_id("OTEC") == 11
        assert await repository.instrument_id("OTEC") == 11
        assert await repository.first("SELECT 1 AS value") == {"value": 1}
        assert await repository.first("SELECT 1 AS value") == {"value": 1}
        await repository.run("UPDATE job_runs SET records_written=records_written")
        assert await repository.first("SELECT 1 AS value") == {"value": 1}

    asyncio.run(run())

    source_reads = [sql for sql, _ in database.read_calls if "FROM sources" in sql]
    instrument_reads = [sql for sql, _ in database.read_calls if "FROM instruments" in sql]
    value_reads = [sql for sql, _ in database.read_calls if "SELECT 1 AS value" in sql]
    assert len(source_reads) == 1
    assert len(instrument_reads) == 1
    assert len(value_reads) == 2  # write invalidates ordinary read cache
    metrics = repository.performance_metrics()
    assert metrics["read_cache_hits"] >= 3
    assert metrics["d1_writes"] == 1


class _PlanRepository:
    def __init__(self, eod_done: bool = False) -> None:
        self.eod_done = eod_done
        self.calls = 0

    async def first(self, sql, parameters=()):
        self.calls += 1
        return {"ok": 1} if self.eod_done else None


def test_otec_plan_avoids_network_window_on_weekend_and_before_open() -> None:
    weekend_repo = _PlanRepository()
    weekend = asyncio.run(
        _otec_refresh_plan(
            weekend_repo,
            datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        )
    )
    assert weekend["should_poll"] is False
    assert weekend["reason"] == "not_trading_day"
    assert weekend_repo.calls == 0

    early_repo = _PlanRepository()
    early = asyncio.run(
        _otec_refresh_plan(
            early_repo,
            datetime(2026, 8, 17, 8, 30, tzinfo=ZoneInfo("Europe/Oslo")),
        )
    )
    assert early["should_poll"] is False
    assert early["reason"] == "before_bootstrap_cutoff"
    assert early_repo.calls == 0


def test_otec_plan_stops_polling_after_eod_marker_exists() -> None:
    repository = _PlanRepository(eod_done=True)
    plan = asyncio.run(
        _otec_refresh_plan(
            repository,
            datetime(2026, 8, 17, 18, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        )
    )
    assert plan["should_poll"] is False
    assert plan["reason"] == "eod_already_finalized"
    assert repository.calls == 1


def _message(message_id: int, title: str) -> NewsWebMessage:
    return NewsWebMessage(
        message_id=message_id,
        news_id=message_id,
        title=title,
        body="body",
        issuer_id=7759,
        issuer_sign="OTEC",
        issuer_name="Otello Corporation ASA",
        published_at="2026-08-17T12:00:00Z",
        markets=("XOSL",),
        category_ids=(),
        attachments=(),
        corrected_by_message_id=0,
        correction_for_message_id=0,
        client_announcement_id=None,
    )


class _NewsRepository:
    async def all(self, sql, parameters=()):
        assert "FROM source_documents" in sql
        return [
            {
                "external_id": "newsweb-message:100",
                "metadata_json": "{}",
            },
            {
                "external_id": "https://newsweb.oslobors.no/message/100",
                "metadata_json": "{}",
            },
        ]


@pytest.mark.parametrize("new_title", ["Quarterly report Q2", "Primary insider notification"])
def test_newsweb_fast_fetches_only_new_message_once(monkeypatch, new_title: str) -> None:
    existing = _message(100, "Share buyback program status")
    new = _message(101, new_title)
    fetched: list[int] = []
    archived: list[int] = []

    async def fake_history_start(_repository):
        return "2026-08-03"

    async def fake_buyback_start(_repository):
        return "2026-07-27"

    async def fake_discover(*args, **kwargs):
        return [existing, new]

    async def fake_fetch(message_id, **kwargs):
        fetched.append(message_id)
        return new if message_id == 101 else existing

    async def fake_archive(_repository, message):
        archived.append(message.message_id)
        return {
            "message_id": message.message_id,
            "source_document_id": 1,
            "company_news_id": 2,
            "category": "OTHER",
            "requires_review": True,
        }

    monkeypatch.setattr(nw_fast, "history_start_for_refresh", fake_history_start)
    monkeypatch.setattr(nw_fast, "buyback_start_for_refresh", fake_buyback_start)
    monkeypatch.setattr(nw_fast, "discover_otec_messages", fake_discover)
    monkeypatch.setattr(nw_fast, "fetch_message", fake_fetch)
    monkeypatch.setattr(nw_fast, "archive_message", fake_archive)

    result = asyncio.run(
        nw_fast.collect_newsweb_fast(_NewsRepository(), to_date="2026-08-17")
    )

    assert fetched == [101]
    assert archived == [101]
    assert result["full_messages_fetched"] == 1
    assert result["skipped_existing"] == 1
    assert result["history"]["archived"] == 1


def test_performance_index_migration_targets_hot_worker_queries() -> None:
    sql = (ROOT / "cloudflare" / "migrations" / "0005_performance_indexes.sql").read_text(
        encoding="utf-8"
    )
    for name in (
        "idx_market_prices_instrument_type_date",
        "idx_fx_rates_pair_calendar_date",
        "idx_nav_snapshots_calc_scope_calendar_date",
        "idx_job_runs_name_status_finished",
        "idx_source_documents_source_published",
    ):
        assert name in sql
