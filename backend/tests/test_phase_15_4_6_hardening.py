from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document as sqlite_create_source_document
from app.marketdata.b3_calendar import is_b3_trading_day as backend_b3_trading_day

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from b3_calendar import is_b3_trading_day as worker_b3_trading_day  # noqa: E402
from bounded_response import read_response_bytes  # noqa: E402
from otec_ingestion import maybe_finalize_otec_eod  # noqa: E402
from repository import D1WriteRepository  # noqa: E402


class _StreamReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = iter(chunks)
        self.cancelled = False
        self.released = False

    async def read(self):
        try:
            return SimpleNamespace(done=False, value=next(self.chunks))
        except StopIteration:
            return SimpleNamespace(done=True, value=None)

    async def cancel(self, _reason: str) -> None:
        self.cancelled = True

    def releaseLock(self) -> None:
        self.released = True


class _StreamBody:
    def __init__(self, reader: _StreamReader) -> None:
        self.reader = reader

    def getReader(self) -> _StreamReader:
        return self.reader


class _StreamResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.reader = _StreamReader(chunks)
        self.body = _StreamBody(self.reader)


class _MemoryD1Repository(D1WriteRepository):
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.next_id = 1

    async def source_id(self, code: str) -> int:
        assert code == "NEWSWEB"
        return 1

    async def first(self, sql: str, parameters=()):
        if "FROM source_documents" not in sql:
            return None
        external_id = parameters[-1]
        for item in reversed(self.documents):
            if item["source_id"] == int(parameters[0]) and item["external_id"] == external_id:
                return {
                    "id": item["id"],
                    "metadata_json": item["metadata_json"],
                    "content_sha256": item["content_sha256"],
                }
        return None

    async def run(self, sql: str, parameters=()):
        compact = " ".join(sql.split())
        if compact.startswith("INSERT INTO source_documents"):
            (
                source_id,
                external_id,
                document_type,
                title,
                published_at,
                url,
                content_sha256,
                metadata_json,
            ) = parameters
            self.documents.append(
                {
                    "id": self.next_id,
                    "source_id": int(source_id),
                    "external_id": external_id,
                    "document_type": document_type,
                    "title": title,
                    "published_at": published_at,
                    "url": url,
                    "content_sha256": content_sha256,
                    "metadata_json": metadata_json,
                }
            )
            self.next_id += 1
            return None
        if compact.startswith("UPDATE source_documents"):
            (
                document_type,
                title,
                url,
                published_at,
                content_sha256,
                metadata_json,
                document_id,
            ) = parameters
            row = next(item for item in self.documents if item["id"] == int(document_id))
            row.update(
                {
                    "document_type": document_type,
                    "title": title,
                    "url": url,
                    "published_at": published_at or row["published_at"],
                    "content_sha256": content_sha256 or row["content_sha256"],
                    "metadata_json": metadata_json,
                }
            )
            return None
        raise AssertionError(f"Unexpected SQL: {compact}")


class _EodRepository:
    def __init__(self) -> None:
        self.latest: dict | None = None
        self.marker_written = False
        self.documents: list[dict] = []
        self.prices: list[dict] = []

    async def first(self, sql: str, parameters=()):
        if "FROM source_documents" in sql:
            return {"ok": 1} if self.marker_written else None
        if "FROM market_prices" in sql:
            return self.latest
        return None

    async def create_source_document(self, **kwargs):
        self.marker_written = True
        self.documents.append(kwargs)
        return 101

    async def upsert_market_price(self, **kwargs):
        self.prices.append(kwargs)
        return 202


def test_b3_republic_day_is_a_recurring_non_trading_day() -> None:
    republic_day = date(2027, 11, 15)
    next_day = date(2027, 11, 16)

    assert republic_day.weekday() == 0
    assert backend_b3_trading_day(republic_day) is False
    assert worker_b3_trading_day(republic_day) is False
    assert backend_b3_trading_day(next_day) is True
    assert worker_b3_trading_day(next_day) is True


def test_bounded_reader_rejects_chunked_response_before_unbounded_buffering() -> None:
    response = _StreamResponse([b"12345", b"67890", b"X"])

    try:
        asyncio.run(read_response_bytes(response, max_bytes=10, label="test payload"))
    except ValueError as exc:
        assert "test payload overstiger Worker-grensen" in str(exc)
    else:
        raise AssertionError("Expected chunked response to be rejected")

    assert response.reader.cancelled is True
    assert response.reader.released is True


def test_bounded_reader_accepts_chunked_response_within_limit() -> None:
    response = _StreamResponse([b"12345", b"67890"])

    payload = asyncio.run(read_response_bytes(response, max_bytes=10, label="test payload"))

    assert payload == b"1234567890"
    assert response.reader.cancelled is False
    assert response.reader.released is True


def test_sqlite_source_document_hash_change_creates_immutable_version(tmp_path) -> None:
    database_path = str(tmp_path / "provenance.db")
    init_database(database_path)

    with get_connection(database_path) as connection:
        original_id = sqlite_create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="newsweb-message:123",
            document_type="REGULATORY_NEWS",
            title="Original",
            url="https://example.test/123",
            published_at="2026-08-17T10:00:00Z",
            content_sha256="a" * 64,
            metadata={"version": 1},
        )
        same_id = sqlite_create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="newsweb-message:123",
            document_type="REGULATORY_NEWS",
            title="Original metadata refresh",
            url="https://example.test/123",
            published_at="2026-08-17T10:00:00Z",
            content_sha256="a" * 64,
            metadata={"refreshed": True},
        )
        changed_id = sqlite_create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="newsweb-message:123",
            document_type="REGULATORY_NEWS",
            title="Corrected body",
            url="https://example.test/123",
            published_at="2026-08-17T10:05:00Z",
            content_sha256="b" * 64,
            metadata={"version": 2},
        )
        repeated_changed_id = sqlite_create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="newsweb-message:123",
            document_type="REGULATORY_NEWS",
            title="Corrected body",
            url="https://example.test/123",
            published_at="2026-08-17T10:05:00Z",
            content_sha256="b" * 64,
            metadata={"version": 2},
        )

        original = connection.execute(
            "SELECT external_id, content_sha256, metadata_json FROM source_documents WHERE id=?",
            (original_id,),
        ).fetchone()
        changed = connection.execute(
            "SELECT external_id, content_sha256, metadata_json FROM source_documents WHERE id=?",
            (changed_id,),
        ).fetchone()

    assert same_id == original_id
    assert changed_id != original_id
    assert repeated_changed_id == changed_id
    assert original["external_id"] == "newsweb-message:123"
    assert original["content_sha256"] == "a" * 64
    assert changed["external_id"] == f"newsweb-message:123#sha256:{'b' * 20}"
    assert changed["content_sha256"] == "b" * 64
    changed_metadata = json.loads(changed["metadata_json"])
    assert changed_metadata["original_source_document_id"] == original_id
    assert changed_metadata["provenance_policy"] == "IMMUTABLE_CONTENT_VERSION"


def test_d1_source_document_hash_change_creates_immutable_version() -> None:
    repository = _MemoryD1Repository()

    async def scenario() -> tuple[int, int, int]:
        original_id = await repository.create_source_document(
            source_code="NEWSWEB",
            external_id="newsweb-message:456",
            document_type="REGULATORY_NEWS",
            title="Original",
            url="https://example.test/456",
            published_at="2026-08-17T10:00:00Z",
            content_sha256="c" * 64,
            metadata={"version": 1},
        )
        changed_id = await repository.create_source_document(
            source_code="NEWSWEB",
            external_id="newsweb-message:456",
            document_type="REGULATORY_NEWS",
            title="Corrected",
            url="https://example.test/456",
            published_at="2026-08-17T10:05:00Z",
            content_sha256="d" * 64,
            metadata={"version": 2},
        )
        repeated_id = await repository.create_source_document(
            source_code="NEWSWEB",
            external_id="newsweb-message:456",
            document_type="REGULATORY_NEWS",
            title="Corrected",
            url="https://example.test/456",
            published_at="2026-08-17T10:05:00Z",
            content_sha256="d" * 64,
            metadata={"version": 2},
        )
        return original_id, changed_id, repeated_id

    original_id, changed_id, repeated_id = asyncio.run(scenario())

    assert original_id != changed_id
    assert repeated_id == changed_id
    assert repository.documents[0]["content_sha256"] == "c" * 64
    assert repository.documents[1]["external_id"] == f"newsweb-message:456#sha256:{'d' * 20}"
    metadata = json.loads(repository.documents[1]["metadata_json"])
    assert metadata["original_source_document_id"] == original_id
    assert metadata["provenance_policy"] == "IMMUTABLE_CONTENT_VERSION"


def test_otec_no_trade_eod_remains_retryable_until_a_trade_exists() -> None:
    repository = _EodRepository()
    now = datetime(2026, 8, 17, 17, 0, tzinfo=ZoneInfo("Europe/Oslo"))
    refresh = {"status": "no_trade", "selected": None, "gap_recovery": False}

    first = asyncio.run(
        maybe_finalize_otec_eod(
            repository=repository,
            now=now,
            current_refresh=refresh,
        )
    )

    assert first["status"] == "no_trade"
    assert first["retryable"] is True
    assert repository.marker_written is False
    assert repository.documents == []

    repository.latest = {
        "id": 77,
        "observed_at": "2026-08-17T14:25:00.000000Z",
        "price": "17.40",
        "currency": "NOK",
        "source_document_id": 55,
        "metadata_json": "{}",
    }
    second = asyncio.run(
        maybe_finalize_otec_eod(
            repository=repository,
            now=now,
            current_refresh=refresh,
        )
    )

    assert second["status"] == "ok"
    assert repository.marker_written is True
    assert repository.documents[0]["external_id"] == "otec-eod-last-check-2026-08-17"
    assert repository.prices[0]["price"] == "17.40"
