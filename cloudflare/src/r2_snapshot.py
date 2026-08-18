from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any, Awaitable, Callable

SNAPSHOT_VERSION = "d1-logical-snapshot-v2-chunked"
SNAPSHOT_CHUNK_ROWS = 500
MAX_CHUNK_UNCOMPRESSED_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_CHUNKS = 750

# Keep the daily logical snapshot focused on financial-model/audit state. High-churn,
# reconstructible operational tables are intentionally excluded; D1 Time Travel remains
# the authoritative whole-database recovery mechanism.
_SNAPSHOT_TABLES: tuple[tuple[str, str], ...] = (
    ("sources", "id"),
    ("instruments", "id"),
    ("source_documents", "id"),
    ("market_prices", "id"),
    ("fx_rates", "id"),
    ("bemobi_holdings", "id"),
    ("corporate_actions", "id"),
    ("cash_anchors", "id"),
    ("cash_movements", "id"),
    ("cash_period_calibrations", "id"),
    ("cash_daily_estimates", "estimate_date"),
    ("buyback_programs", "id"),
    ("buybacks", "id"),
    ("buyback_daily_transactions", "id"),
    ("otello_share_counts", "id"),
    ("other_net_assets_reported_anchors", "id"),
    ("other_net_assets_anchors", "id"),
    ("other_net_assets_daily_estimates", "estimate_date"),
    ("nav_snapshots", "id"),
    ("provenance_records", "id"),
)
_EXCLUDED_RECONSTRUCTIBLE_TABLES = ("company_news", "market_activity", "runtime_state")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _reader(repository) -> Callable[..., Awaitable[list[dict[str, Any]]]]:
    return getattr(repository, "all_uncached", repository.all)


async def _table_chunks(repository, table: str, order_by: str):
    read = _reader(repository)
    cursor: Any | None = None
    chunk_index = 0
    while True:
        if cursor is None:
            rows = await read(
                f"SELECT * FROM {table} ORDER BY {order_by} LIMIT ?",
                (SNAPSHOT_CHUNK_ROWS,),
            )
        else:
            rows = await read(
                f"SELECT * FROM {table} WHERE {order_by} > ? "
                f"ORDER BY {order_by} LIMIT ?",
                (cursor, SNAPSHOT_CHUNK_ROWS),
            )
        if not rows:
            break
        yield chunk_index, rows
        next_cursor = rows[-1].get(order_by)
        if next_cursor is None or next_cursor == cursor:
            raise ValueError(f"D1 snapshot cursor stoppet for {table}.{order_by}")
        cursor = next_cursor
        chunk_index += 1


async def archive_d1_snapshot(
    repository,
    bucket,
    *,
    target_date: str,
    preflight_status: str | None = None,
) -> dict[str, Any]:
    """Write a chunked financial audit snapshot without a whole-database memory copy."""
    row_counts: dict[str, int] = {}
    chunks: list[dict[str, Any]] = []
    total_uncompressed = 0
    total_compressed = 0

    for table, order_by in _SNAPSHOT_TABLES:
        table_rows = 0
        async for chunk_index, rows in _table_chunks(repository, table, order_by):
            if len(chunks) >= MAX_SNAPSHOT_CHUNKS:
                raise ValueError(
                    f"D1 logical snapshot overstiger grensen på {MAX_SNAPSHOT_CHUNKS} chunks"
                )
            chunk_payload = {
                "snapshot_version": SNAPSHOT_VERSION,
                "target_date": target_date,
                "table": table,
                "order_by": order_by,
                "chunk_index": chunk_index,
                "rows": rows,
            }
            raw = _canonical_json(chunk_payload)
            if len(raw) > MAX_CHUNK_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"D1 snapshot chunk {table}/{chunk_index} overstiger "
                    f"{MAX_CHUNK_UNCOMPRESSED_BYTES} bytes før gzip"
                )
            logical_sha256 = hashlib.sha256(raw).hexdigest()
            compressed = gzip.compress(raw, compresslevel=6, mtime=0)
            total_uncompressed += len(raw)
            total_compressed += len(compressed)
            key = (
                f"snapshots/d1/{target_date}/{table}/"
                f"part-{chunk_index:05d}-{logical_sha256[:20]}.json.gz"
            )
            await bucket.put(key, compressed)
            chunks.append(
                {
                    "table": table,
                    "chunk_index": chunk_index,
                    "row_count": len(rows),
                    "first_key": rows[0].get(order_by),
                    "last_key": rows[-1].get(order_by),
                    "key": key,
                    "logical_sha256": logical_sha256,
                    "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
                    "uncompressed_bytes": len(raw),
                    "compressed_bytes": len(compressed),
                }
            )
            table_rows += len(rows)
        row_counts[table] = table_rows

    logical_manifest = {
        "snapshot_version": SNAPSHOT_VERSION,
        "target_date": target_date,
        "tables": list(row_counts),
        "row_counts": row_counts,
        "chunks": [
            {
                "table": item["table"],
                "chunk_index": item["chunk_index"],
                "logical_sha256": item["logical_sha256"],
                "row_count": item["row_count"],
            }
            for item in chunks
        ],
    }
    digest = hashlib.sha256(_canonical_json(logical_manifest)).hexdigest()
    manifest_key = f"snapshots/d1/{target_date}/manifest-{digest[:20]}.json"
    manifest = {
        **logical_manifest,
        "logical_sha256": digest,
        "uncompressed_bytes": total_uncompressed,
        "compressed_bytes": total_compressed,
        "table_count": len(_SNAPSHOT_TABLES),
        "chunk_count": len(chunks),
        "chunk_rows": SNAPSHOT_CHUNK_ROWS,
        "max_snapshot_chunks": MAX_SNAPSHOT_CHUNKS,
        "chunk_objects": chunks,
        "excluded_reconstructible_tables": list(_EXCLUDED_RECONSTRUCTIBLE_TABLES),
        "preflight_status": preflight_status,
        "restore_scope": "LOGICAL_AUDIT_SNAPSHOT_NOT_D1_TIME_TRAVEL_REPLACEMENT",
    }
    await bucket.put(manifest_key, _canonical_json(manifest))
    return {
        "status": "ok",
        **manifest,
        "manifest_key": manifest_key,
    }
