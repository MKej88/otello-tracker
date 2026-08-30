from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


_MISSING = object()


def _to_python(value: Any) -> Any:
    """Convert Worker/Pyodide JS proxy values to ordinary Python containers."""
    converter = getattr(value, "to_py", None)
    if callable(converter):
        try:
            value = converter()
        except (TypeError, RuntimeError):
            pass

    if isinstance(value, Mapping):
        return {str(key): _to_python(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_python(item) for item in value]

    items = getattr(value, "items", None)
    if callable(items):
        try:
            return {str(key): _to_python(item) for key, item in items()}
        except (TypeError, RuntimeError):
            pass
    return value


def _versioned_external_id(external_id: str, content_sha256: str) -> str:
    return f"{external_id}#sha256:{content_sha256[:20]}"


class D1Repository:
    """Minimal data-access layer for dashboard API queries."""

    def __init__(self, database: Any):
        self.database = database

    async def all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        statement = self.database.prepare(sql)
        if parameters:
            statement = statement.bind(*parameters)
        result = await statement.all()
        raw_rows = getattr(result, "results", _MISSING)
        if raw_rows is _MISSING:
            raise RuntimeError("D1-svaret mangler det forventede 'results'-feltet")

        rows = _to_python(raw_rows)
        if rows is None:
            raise RuntimeError("D1-svaret har null i det forventede 'results'-feltet")
        if isinstance(rows, Mapping):
            rows = [rows]
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise RuntimeError("D1-svarets 'results'-felt er ikke en liste med rader")

        converted_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise RuntimeError("D1-svaret inneholder en rad som ikke er et objekt")
            converted_rows.append(dict(row))
        return converted_rows

    async def first(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None


class D1WriteRepository(D1Repository):
    """Bound, idempotent D1 writes used by scheduled ingestion.

    Content-bearing source documents are immutable across hash changes. A changed body
    under the same provider ID is stored as a content-addressed version row so existing
    facts retain the exact source snapshot they originally referenced.
    """

    async def run(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        statement = self.database.prepare(sql)
        if parameters:
            statement = statement.bind(*parameters)
        return await statement.run()

    async def source_id(self, code: str) -> int:
        row = await self.first("SELECT id FROM sources WHERE code=?", (code,))
        if row is None:
            raise ValueError(f"Ukjent kildekode: {code}")
        return int(row["id"])

    async def instrument_id(self, symbol: str) -> int:
        row = await self.first("SELECT id FROM instruments WHERE symbol=?", (symbol,))
        if row is None:
            raise ValueError(f"Ukjent instrument: {symbol}")
        return int(row["id"])

    async def create_source_document(
        self,
        *,
        source_code: str,
        document_type: str,
        title: str,
        url: str,
        external_id: str | None = None,
        published_at: str | None = None,
        content_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        sid = await self.source_id(source_code)
        metadata = metadata or {}

        existing = None
        if external_id is not None:
            existing = await self.first(
                """
                SELECT id, metadata_json, content_sha256
                FROM source_documents
                WHERE source_id=? AND external_id=?
                LIMIT 1
                """,
                (sid, external_id),
            )
        if existing is not None:
            previous_hash = str(existing.get("content_sha256") or "")
            if content_sha256 and previous_hash and content_sha256 != previous_hash:
                version_external_id = _versioned_external_id(external_id, content_sha256)
                version = await self.first(
                    """
                    SELECT id FROM source_documents
                    WHERE source_id=? AND external_id=?
                    LIMIT 1
                    """,
                    (sid, version_external_id),
                )
                if version is not None:
                    return int(version["id"])

                version_metadata = {
                    **metadata,
                    "logical_external_id": external_id,
                    "content_version_sha256": content_sha256,
                    "original_source_document_id": int(existing["id"]),
                    "provenance_policy": "IMMUTABLE_CONTENT_VERSION",
                }
                await self.run(
                    """
                    INSERT INTO source_documents(
                        source_id, external_id, document_type, title, published_at, url,
                        content_sha256, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        version_external_id,
                        document_type,
                        title,
                        published_at,
                        url,
                        content_sha256,
                        json.dumps(version_metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )
                version = await self.first(
                    """
                    SELECT id FROM source_documents
                    WHERE source_id=? AND external_id=?
                    LIMIT 1
                    """,
                    (sid, version_external_id),
                )
                if version is None:
                    raise RuntimeError("D1 source_document-versjon ble skrevet, men kunne ikke leses tilbake")
                return int(version["id"])

            try:
                previous = json.loads(str(existing.get("metadata_json") or "{}"))
            except (TypeError, json.JSONDecodeError):
                previous = {}
            merged = {**previous, **metadata}
            await self.run(
                """
                UPDATE source_documents
                SET document_type=?, title=?, url=?,
                    published_at=COALESCE(?, published_at),
                    content_sha256=COALESCE(?, content_sha256),
                    metadata_json=?,
                    fetched_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id=?
                """,
                (
                    document_type,
                    title,
                    url,
                    published_at,
                    content_sha256,
                    json.dumps(merged, ensure_ascii=False, sort_keys=True),
                    int(existing["id"]),
                ),
            )
            return int(existing["id"])

        await self.run(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, published_at, url,
                content_sha256, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                external_id,
                document_type,
                title,
                published_at,
                url,
                content_sha256,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            ),
        )
        row = await self.first(
            """
            SELECT id
            FROM source_documents
            WHERE source_id=? AND external_id IS ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (sid, external_id),
        )
        if row is None:
            raise RuntimeError("D1 source_document ble skrevet, men kunne ikke leses tilbake")
        return int(row["id"])

    async def upsert_market_price(
        self,
        *,
        symbol: str,
        observed_at: str,
        trading_date: str,
        price_type: str,
        price: str,
        currency: str,
        source_code: str,
        source_document_id: int | None = None,
        quality: str = "DIRECT",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        iid = await self.instrument_id(symbol)
        sid = await self.source_id(source_code)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        await self.run(
            """
            INSERT INTO market_prices(
                instrument_id, observed_at, trading_date, price_type, price,
                currency, source_id, source_document_id, quality, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instrument_id, observed_at, price_type, source_id)
            DO UPDATE SET
                trading_date=excluded.trading_date,
                price=excluded.price,
                currency=excluded.currency,
                source_document_id=excluded.source_document_id,
                quality=excluded.quality,
                metadata_json=excluded.metadata_json,
                fetched_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (
                iid,
                observed_at,
                trading_date,
                price_type,
                price,
                currency,
                sid,
                source_document_id,
                quality,
                metadata_json,
            ),
        )
        row = await self.first(
            """
            SELECT id FROM market_prices
            WHERE instrument_id=? AND observed_at=? AND price_type=? AND source_id=?
            LIMIT 1
            """,
            (iid, observed_at, price_type, sid),
        )
        if row is None:
            raise RuntimeError("D1 market_price ble skrevet, men kunne ikke leses tilbake")
        return int(row["id"])

    async def start_job(
        self,
        *,
        job_name: str,
        started_at: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        await self.run(
            """
            INSERT INTO job_runs(job_name, started_at, status, metadata_json)
            VALUES (?, ?, 'RUNNING', ?)
            """,
            (job_name, started_at, json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)),
        )
        row = await self.first(
            """
            SELECT id FROM job_runs
            WHERE job_name=? AND started_at=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (job_name, started_at),
        )
        if row is None:
            raise RuntimeError("D1 job_run ble skrevet, men kunne ikke leses tilbake")
        return int(row["id"])

    async def finish_job(
        self,
        job_id: int,
        *,
        finished_at: str,
        status: str,
        records_written: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.run(
            """
            UPDATE job_runs
            SET finished_at=?, status=?, records_written=?, error_message=?, metadata_json=?
            WHERE id=?
            """,
            (
                finished_at,
                status,
                records_written,
                error_message,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                job_id,
            ),
        )

    async def fail_job_if_running(
        self,
        job_id: int,
        *,
        finished_at: str,
        error_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically mark a still-running job FAILED without overwriting a terminal result."""
        row = await self.first(
            "SELECT status, metadata_json FROM job_runs WHERE id=? LIMIT 1",
            (job_id,),
        )
        if row is None or str(row.get("status") or "").upper() != "RUNNING":
            return False

        try:
            existing_metadata = json.loads(str(row.get("metadata_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            existing_metadata = {}
        if not isinstance(existing_metadata, dict):
            existing_metadata = {}
        merged_metadata = {**existing_metadata, **(metadata or {})}
        clipped_error = error_message[:4000] or None

        await self.run(
            """
            UPDATE job_runs
            SET finished_at=?, status='FAILED', records_written=0,
                error_message=?, metadata_json=?
            WHERE id=? AND status='RUNNING'
            """,
            (
                finished_at,
                clipped_error,
                json.dumps(merged_metadata, ensure_ascii=False, sort_keys=True),
                job_id,
            ),
        )
        final_row = await self.first(
            "SELECT status, finished_at, error_message FROM job_runs WHERE id=? LIMIT 1",
            (job_id,),
        )
        return bool(
            final_row
            and str(final_row.get("status") or "").upper() == "FAILED"
            and str(final_row.get("finished_at") or "") == finished_at
            and (final_row.get("error_message") or None) == clipped_error
        )
