from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def decimal_text(value: Decimal | str | int | float) -> str:
    """Store financial values as exact decimal text, never binary floats."""
    return format(Decimal(str(value)), "f")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def source_id(connection: sqlite3.Connection, code: str) -> int:
    row = connection.execute("SELECT id FROM sources WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ValueError(f"Ukjent kildekode: {code}")
    return int(row["id"])


def instrument_id(connection: sqlite3.Connection, symbol: str) -> int:
    row = connection.execute("SELECT id FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    if row is None:
        raise ValueError(f"Ukjent instrument: {symbol}")
    return int(row["id"])


def create_source_document(
    connection: sqlite3.Connection,
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
    """Create or refresh a source document without discarding prior provenance metadata."""
    sid = source_id(connection, source_code)

    if external_id is not None:
        existing = connection.execute(
            """
            SELECT id, metadata_json, published_at, content_sha256
            FROM source_documents
            WHERE source_id = ? AND external_id = ?
            """,
            (sid, external_id),
        ).fetchone()
        if existing is not None:
            try:
                previous_metadata = json.loads(existing["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                previous_metadata = {}
            merged_metadata = {**previous_metadata, **(metadata or {})}
            connection.execute(
                """
                UPDATE source_documents
                SET document_type = ?, title = ?, url = ?,
                    published_at = COALESCE(?, published_at),
                    content_sha256 = COALESCE(?, content_sha256),
                    metadata_json = ?,
                    fetched_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (
                    document_type,
                    title,
                    url,
                    published_at,
                    content_sha256,
                    json.dumps(merged_metadata, ensure_ascii=False, sort_keys=True),
                    existing["id"],
                ),
            )
            return int(existing["id"])

    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    cursor = connection.execute(
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
            metadata_json,
        ),
    )
    return int(cursor.lastrowid)


def upsert_market_price(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    observed_at: str,
    trading_date: str,
    price_type: str,
    price: Decimal | str | int | float,
    currency: str,
    source_code: str,
    source_document_id: int | None = None,
    quality: str = "DIRECT",
    metadata: dict[str, Any] | None = None,
) -> int:
    iid = instrument_id(connection, symbol)
    sid = source_id(connection, source_code)
    price_value = decimal_text(price)
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)

    connection.execute(
        """
        INSERT INTO market_prices(
            instrument_id, observed_at, trading_date, price_type, price,
            currency, source_id, source_document_id, quality, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instrument_id, observed_at, price_type, source_id)
        DO UPDATE SET
            trading_date = excluded.trading_date,
            price = excluded.price,
            currency = excluded.currency,
            source_document_id = excluded.source_document_id,
            quality = excluded.quality,
            metadata_json = excluded.metadata_json,
            fetched_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            iid,
            observed_at,
            trading_date,
            price_type,
            price_value,
            currency,
            sid,
            source_document_id,
            quality,
            metadata_json,
        ),
    )

    row = connection.execute(
        """
        SELECT id FROM market_prices
        WHERE instrument_id = ? AND observed_at = ? AND price_type = ? AND source_id = ?
        """,
        (iid, observed_at, price_type, sid),
    ).fetchone()
    return int(row["id"])


def upsert_fx_rate(
    connection: sqlite3.Connection,
    *,
    base_currency: str,
    quote_currency: str,
    observed_at: str,
    rate: Decimal | str | int | float,
    source_code: str,
    source_document_id: int | None = None,
) -> int:
    sid = source_id(connection, source_code)
    rate_value = decimal_text(rate)

    connection.execute(
        """
        INSERT INTO fx_rates(
            base_currency, quote_currency, observed_at, rate, source_id, source_document_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(base_currency, quote_currency, observed_at, source_id)
        DO UPDATE SET
            rate = excluded.rate,
            source_document_id = excluded.source_document_id,
            fetched_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            base_currency,
            quote_currency,
            observed_at,
            rate_value,
            sid,
            source_document_id,
        ),
    )

    row = connection.execute(
        """
        SELECT id FROM fx_rates
        WHERE base_currency = ? AND quote_currency = ? AND observed_at = ? AND source_id = ?
        """,
        (base_currency, quote_currency, observed_at, sid),
    ).fetchone()
    return int(row["id"])


def record_provenance(
    connection: sqlite3.Connection,
    *,
    entity_table: str,
    entity_id: int,
    field_name: str,
    source_document_id: int,
    extraction_method: str,
    source_locator: str | None = None,
    confidence: str = "HIGH",
    extracted_value: str | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO provenance_records(
            entity_table, entity_id, field_name, source_document_id,
            source_locator, extraction_method, confidence, extracted_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_table,
            entity_id,
            field_name,
            source_document_id,
            source_locator,
            extraction_method,
            confidence,
            extracted_value,
        ),
    )
    return int(cursor.lastrowid)
