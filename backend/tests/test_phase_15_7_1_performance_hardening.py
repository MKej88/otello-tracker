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


def _weekly_row(
    *,
    weekly_id: int = 10,
    trade_date: str = "2026-08-14",
    source_document_id: int = 101,
    shares: int = 300,
    amount_nok: str = "3000",
    daily: str = "2026-08-14",
) -> dict:
    return {
        "weekly_id": weekly_id,
        "latest_weekly_date": trade_date,
        "weekly_source_document_id": source_document_id,
        "weekly_shares": shares,
        "weekly_amount_nok": amount_nok,
        "latest_daily_date": daily,
    }


class _PdfRepository:
    def __init__(
        self,
        *,
        row: dict | None = None,
        completed_fingerprint: str | None = None,
        last_success: str | None = "2026-08-01",
    ) -> None:
        self.row = row or _weekly_row()
        if completed_fingerprint == "CURRENT":
            completed_fingerprint = newsweb_pdf_refresh._weekly_fingerprint(self.row)
        self.runtime: dict[str, str] = {}
        if completed_fingerprint is not None:
            self.runtime[newsweb_pdf_refresh._COMPLETED_WEEKLY_KEY] = completed_fingerprint
        if last_success is not None:
            self.runtime[newsweb_pdf_refresh._LAST_SUCCESS_KEY] = last_success
        self.writes: list[tuple[str, str]] = []

    async def first(self, sql: str, parameters=()):
        if "FROM buybacks b" in sql:
            return dict(self.row)
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
    repository = _PdfRepository(completed_fingerprint="CURRENT")
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


def test_newsweb_pdf_refresh_runs_when_weekly_fingerprint_changes(monkeypatch) -> None:
    calls = 0
    old = _weekly_row(
        weekly_id=9,
        trade_date="2026-08-07",
        source_document_id=99,
        shares=250,
        amount_nok="2500",
    )

    async def heavy(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "ok", "pdfs_archived": 1, "daily_rows_written": 2}

    monkeypatch.setattr(newsweb_pdf_refresh, "enrich_newsweb_buybacks_with_r2", heavy)
    repository = _PdfRepository(
        completed_fingerprint=newsweb_pdf_refresh._weekly_fingerprint(old),
        last_success="2026-08-15",
    )
    result = asyncio.run(
        newsweb_pdf_refresh.enrich_newsweb_buybacks_if_due(
            repository,
            _Bucket(),
            target_date="2026-08-17",
        )
    )
    assert result["status"] == "ok"
    assert result["skipped"] is False
    assert result["refresh_reason"] == "weekly_fingerprint_changed"
    assert calls == 1
    assert repository.runtime[newsweb_pdf_refresh._COMPLETED_WEEKLY_KEY] == (
        newsweb_pdf_refresh._weekly_fingerprint(repository.row)
    )
    assert repository.runtime[newsweb_pdf_refresh._LAST_SUCCESS_KEY] == "2026-08-17"


def test_newsweb_pdf_same_date_correction_changes_fingerprint(monkeypatch) -> None:
    calls = 0
    current = _weekly_row(source_document_id=102, amount_nok="3010")
    old_same_date = _weekly_row(source_document_id=101, amount_nok="3000")

    async def heavy(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "ok"}

    monkeypatch.setattr(newsweb_pdf_refresh, "enrich_newsweb_buybacks_with_r2", heavy)
    repository = _PdfRepository(
        row=current,
        completed_fingerprint=newsweb_pdf_refresh._weekly_fingerprint(old_same_date),
        last_success="2026-08-16",
    )
    result = asyncio.run(
        newsweb_pdf_refresh.enrich_newsweb_buybacks_if_due(
            repository,
            _Bucket(),
            target_date="2026-08-17",
        )
    )
    assert result["refresh_reason"] == "weekly_fingerprint_changed"
    assert calls == 1


def test_newsweb_pdf_partial_does_not_advance_markers(monkeypatch) -> None:
    old = _weekly_row(weekly_id=9, trade_date="2026-08-07", source_document_id=99)
    old_fingerprint = newsweb_pdf_refresh._weekly_fingerprint(old)

    async def heavy(*_args, **_kwargs):
        return {"status": "partial", "errors": [{"error": "temporary"}]}

    monkeypatch.setattr(newsweb_pdf_refresh, "enrich_newsweb_buybacks_with_r2", heavy)
    repository = _PdfRepository(
        completed_fingerprint=old_fingerprint,
        last_success="2026-08-15",
    )
    result = asyncio.run(
        newsweb_pdf_refresh.enrich_newsweb_buybacks_if_due(
            repository,
            _Bucket(),
            target_date="2026-08-17",
        )
    )
    assert result["status"] == "partial"
    assert repository.runtime[newsweb_pdf_refresh._COMPLETED_WEEKLY_KEY] == old_fingerprint
    assert repository.runtime[newsweb_pdf_refresh._LAST_SUCCESS_KEY] == "2026-08-15"
    assert repository.writes == []


def test_newsweb_pdf_revalidates_after_30_days(monkeypatch) -> None:
    calls = 0

    async def heavy(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "ok", "pdfs_archived": 0}

    monkeypatch.setattr(newsweb_pdf_refresh, "enrich_newsweb_buybacks_with_r2", heavy)
    repository = _PdfRepository(
        completed_fingerprint="CURRENT",
        last_success="2026-07-18",
    )
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
