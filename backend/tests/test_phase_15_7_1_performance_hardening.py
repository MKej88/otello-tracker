from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import newsweb_pdf_refresh  # noqa: E402
from bounded_response import read_response_buffer  # noqa: E402
from newsweb_daily_buybacks import PARSER_VERSION  # noqa: E402
from otec_workflow_recovery import MAX_WORKFLOW_ZIP_BYTES  # noqa: E402
from r2_snapshot import (  # noqa: E402
    SNAPSHOT_CHUNK_ROWS,
    _EXCLUDED_RECONSTRUCTIBLE_TABLES,
)


class _Reader:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.cancelled = False
        self.released = False

    async def read(self):
        if not self.chunks:
            return SimpleNamespace(done=True, value=None)
        return SimpleNamespace(done=False, value=self.chunks.pop(0))

    async def cancel(self, _reason: str):
        self.cancelled = True

    def releaseLock(self):
        self.released = True


class _Body:
    def __init__(self, reader: _Reader) -> None:
        self.reader = reader

    def getReader(self):
        return self.reader


class _Response:
    def __init__(self, chunks: list[bytes]) -> None:
        self.reader = _Reader(chunks)
        self.body = _Body(self.reader)
        self.headers = {"content-length": str(sum(len(item) for item in chunks))}


def test_bounded_stream_uses_single_mutable_buffer() -> None:
    response = _Response([b"abc", b"def"])
    payload = asyncio.run(read_response_buffer(response, max_bytes=10, label="test"))
    assert isinstance(payload, bytearray)
    assert payload == bytearray(b"abcdef")
    assert response.reader.released is True


def test_snapshot_is_bounded_and_excludes_reconstructible_tables() -> None:
    assert SNAPSHOT_CHUNK_ROWS == 500
    assert set(_EXCLUDED_RECONSTRUCTIBLE_TABLES) == {
        "company_news",
        "market_activity",
        "runtime_state",
    }


def test_otec_workflow_recovery_has_conservative_zip_cap() -> None:
    assert MAX_WORKFLOW_ZIP_BYTES == 28 * 1024 * 1024


class _PdfRepository:
    def __init__(
        self,
        *,
        weekly: str = "2026-08-14",
        daily: str = "2026-08-14",
        completed: str | None = "2026-08-14",
        last_success: str | None = "2026-08-01",
    ) -> None:
        self.weekly = weekly
        self.daily = daily
        self.runtime: dict[str, str] = {}
        if completed is not None:
            self.runtime[newsweb_pdf_refresh._COMPLETED_WEEKLY_KEY] = completed
        if last_success is not None:
            self.runtime[newsweb_pdf_refresh._LAST_SUCCESS_KEY] = last_success
        self.writes: list[tuple[str, str]] = []

    async def first(self, sql: str, parameters=()):
        if "MAX(trade_date) FROM buybacks" in sql:
            return {
                "latest_weekly_date": self.weekly,
                "latest_daily_date": self.daily,
            }
        if "FROM runtime_state" in sql:
            value = self.runtime.get(str(parameters[0]))
            return {"value": value} if value is not None else None
        raise AssertionError(f"Unexpected first query: {sql}")

    async def all(self, sql: str, parameters=()):
        if "BUYBACK_TRANSACTION_ATTACHMENT" in sql:
            return [
                {
                    "id": 1,
                    "fetched_at": "2026-08-01T03:30:00Z",
                    "content_sha256": "a" * 64,
                    "metadata_json": json.dumps(
                        {
                            "parser": PARSER_VERSION,
                            "r2_key": "raw/newsweb/example.pdf",
                            "weekly_reconciliation": {"quality": "CONFIRMED"},
                        }
                    ),
                }
            ]
        raise AssertionError(f"Unexpected all query: {sql}")

    async def run(self, sql: str, parameters=()):
        if "runtime_state" not in sql:
            raise AssertionError(f"Unexpected write: {sql}")
        key, value = str(parameters[0]), str(parameters[1])
        self.runtime[key] = value
        self.writes.append((key, value))
        return {"ok": True}


class _Bucket:
    pass


def test_newsweb_pdf_refresh_skips_current_coverage(monkeypatch) -> None:
    calls = 0

    async def heavy(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("heavy PDF refresh should have been skipped")

    monkeypatch.setattr(newsweb_pdf_refresh, "enrich_newsweb_buybacks_with_r2", heavy)
    repository = _PdfRepository()
    result = asyncio.run(
        newsweb_pdf_refresh.enrich_newsweb_buybacks_if_due(
            repository,
            _Bucket(),
            target_date="2026-08-17",
        )
    )
    assert result["status"] == "ok"
    assert result["skipped"] is True
    assert result["reason"] == "pdf_coverage_current"
    assert calls == 0
    assert repository.writes == []


def test_newsweb_pdf_refresh_runs_for_new_week_and_advances_markers(monkeypatch) -> None:
    calls = 0

    async def heavy(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "ok", "pdfs_archived": 1, "daily_rows_written": 2}

    monkeypatch.setattr(newsweb_pdf_refresh, "enrich_newsweb_buybacks_with_r2", heavy)
    repository = _PdfRepository(completed="2026-08-07", last_success="2026-08-15")
    result = asyncio.run(
        newsweb_pdf_refresh.enrich_newsweb_buybacks_if_due(
            repository,
            _Bucket(),
            target_date="2026-08-17",
        )
    )
    assert result["status"] == "ok"
    assert result["skipped"] is False
    assert result["refresh_reason"] == "new_weekly_coverage"
    assert calls == 1
    assert repository.runtime[newsweb_pdf_refresh._COMPLETED_WEEKLY_KEY] == "2026-08-14"
    assert repository.runtime[newsweb_pdf_refresh._LAST_SUCCESS_KEY] == "2026-08-17"


def test_newsweb_pdf_partial_does_not_advance_markers(monkeypatch) -> None:
    async def heavy(*_args, **_kwargs):
        return {"status": "partial", "errors": [{"error": "temporary"}]}

    monkeypatch.setattr(newsweb_pdf_refresh, "enrich_newsweb_buybacks_with_r2", heavy)
    repository = _PdfRepository(completed="2026-08-07", last_success="2026-08-15")
    result = asyncio.run(
        newsweb_pdf_refresh.enrich_newsweb_buybacks_if_due(
            repository,
            _Bucket(),
            target_date="2026-08-17",
        )
    )
    assert result["status"] == "partial"
    assert repository.runtime[newsweb_pdf_refresh._COMPLETED_WEEKLY_KEY] == "2026-08-07"
    assert repository.runtime[newsweb_pdf_refresh._LAST_SUCCESS_KEY] == "2026-08-15"
    assert repository.writes == []


def test_newsweb_pdf_revalidates_after_30_days(monkeypatch) -> None:
    calls = 0

    async def heavy(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "ok", "pdfs_archived": 0}

    monkeypatch.setattr(newsweb_pdf_refresh, "enrich_newsweb_buybacks_with_r2", heavy)
    repository = _PdfRepository(last_success="2026-07-18")
    result = asyncio.run(
        newsweb_pdf_refresh.enrich_newsweb_buybacks_if_due(
            repository,
            _Bucket(),
            target_date="2026-08-17",
        )
    )
    assert result["refresh_reason"] == "periodic_hash_revalidation"
    assert calls == 1
    assert repository.runtime[newsweb_pdf_refresh._LAST_SUCCESS_KEY] == "2026-08-17"
