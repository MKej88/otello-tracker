from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

SNAPSHOT_VERSION = "d1-logical-snapshot-v3-cost-bounded"
SNAPSHOT_CHUNK_ROWS = 500
MAX_CHUNK_UNCOMPRESSED_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_CHUNKS = 750

# D1 Time Travel on Workers Paid covers short-term point-in-time recovery. The separate R2
# logical snapshot is therefore an audit/long-retention layer rather than a daily backup.
# Keep weekly checkpoints plus every calendar month-end; this bounds R2 storage growth and
# Class A writes without changing the financial model or D1 recovery path.
_SNAPSHOT_TABLES: tuple[tuple[str, str], ...] = (
    ("sources", "id"),
    ("instruments", "id"),
    ("source_documents", "id"),
    ("market_prices", "id"),
    ("fx_rates", "id"),
    ("bemobi_holdings", "id"),
    ("bemobi_investor_facts", "id"),
    ("bemobi_quarter_actuals", "period"),
    ("bemobi_forward_consensus_snapshots", "id"),
    ("bemobi_consensus_events", "id"),
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
    ("broker_estimate_sets", "id"),
    ("broker_estimate_values", "id"),
    ("consensus_snapshots", "id"),
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


def should_archive_d1_snapshot(target_date: str) -> bool:
    current = date.fromisoformat(target_date)
    next_day = current + timedelta(days=1)
    is_sunday = current.weekday() == 6
    is_month_end = next_day.month != current.month
    return is_sunday or is_month_end


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
                (cursor, SNAPSHOT_CHUNK_ROWS,),
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
    force: bool = False,
) -> dict[str, Any]:
    """Write a bounded weekly/month-end financial audit snapshot to R2."""
    if not force and not should_archive_d1_snapshot(target_date):
        return {
            "status": "skipped",
            "reason": "weekly_or_month_end_only",
            "target_date": target_date,
            "d1_time_travel_is_primary_short_term_recovery": True,
        }

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
        "retention_policy": "WEEKLY_PLUS_MONTH_END",
        "restore_scope": "LOGICAL_AUDIT_SNAPSHOT_NOT_D1_TIME_TRAVEL_REPLACEMENT",
    }
    await bucket.put(manifest_key, _canonical_json(manifest))

    # Do not return the full chunk manifest into Workflow state. The complete manifest is
    # already durable in R2; only the compact result is needed by orchestration/job logs.
    return {
        "status": "ok",
        "snapshot_version": SNAPSHOT_VERSION,
        "target_date": target_date,
        "logical_sha256": digest,
        "uncompressed_bytes": total_uncompressed,
        "compressed_bytes": total_compressed,
        "table_count": len(_SNAPSHOT_TABLES),
        "chunk_count": len(chunks),
        "manifest_key": manifest_key,
        "preflight_status": preflight_status,
        "retention_policy": "WEEKLY_PLUS_MONTH_END",
    }



async def verify_snapshot_readback(
    bucket, result: dict[str, Any], *, full: bool = False
) -> dict[str, Any]:
    """Validate sampled chunks, or all chunks during quarterly recovery rehearsal.

    Even full readback verifies logical integrity, not D1 schema/point-in-time
    restoration. Never writes production D1. Use isolated D1 for actual restores.
    """
    manifest_key = str(result["manifest_key"])
    manifest_obj = await bucket.get(manifest_key)
    if manifest_obj is None:
        raise ValueError("R2 snapshot manifest could not be read back")
    manifest = json.loads(await manifest_obj.text())
    logical = {
        name: manifest[name] for name in (
            "snapshot_version", "target_date", "tables", "row_counts", "chunks"
        )
    }
    digest = hashlib.sha256(_canonical_json(logical)).hexdigest()
    if (
        digest != result["logical_sha256"]
        or digest != manifest.get("logical_sha256")
        or manifest.get("snapshot_version") != SNAPSHOT_VERSION
        or manifest.get("target_date") != result["target_date"]
    ):
        raise ValueError("R2 snapshot manifest integrity check failed")

    entries = manifest.get("chunk_objects") or []
    tables = manifest.get("tables") or []
    if (
        len(entries) != result["chunk_count"]
        or len(entries) != manifest.get("chunk_count")
        or len(tables) != manifest.get("table_count")
        or len(entries) > MAX_SNAPSHOT_CHUNKS
    ):
        raise ValueError("R2 snapshot manifest counts do not agree")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        table = str(entry["table"])
        key = str(entry["key"])
        if (
            table not in tables
            or not key.startswith(
                "snapshots/d1/" + result["target_date"] + "/" + table + "/"
            )
        ):
            raise ValueError("Unexpected snapshot object path")
        grouped.setdefault(table, []).append(entry)
    if sum(int(entry["row_count"]) for entry in entries) != sum(
        int(count) for count in manifest["row_counts"].values()
    ):
        raise ValueError("R2 snapshot row counts differ")
    if not grouped:
        raise ValueError("No populated R2 snapshot tables to read back")

    selected = {
        entry["key"]: entry
        for rows in grouped.values()
        for entry in (rows if full else (rows[0], rows[-1]))
    }
    checked_rows = 0
    verified_by_table: dict[str, int] = {}
    last_key_by_table: dict[str, Any] = {}
    for key, entry in selected.items():
        obj = await bucket.get(key)
        if obj is None:
            raise ValueError("R2 snapshot chunk is missing: " + key)
        body = await obj.arrayBuffer()
        compressed = bytes(body.to_py() if hasattr(body, "to_py") else body)
        if hashlib.sha256(compressed).hexdigest() != entry["compressed_sha256"]:
            raise ValueError("R2 snapshot compressed digest mismatch: " + key)
        raw = gzip.decompress(compressed)
        if hashlib.sha256(raw).hexdigest() != entry["logical_sha256"]:
            raise ValueError("R2 snapshot logical digest mismatch: " + key)
        chunk = json.loads(raw)
        if (
            chunk["snapshot_version"] != SNAPSHOT_VERSION
            or chunk["target_date"] != result["target_date"]
            or chunk["table"] != entry["table"]
            or chunk["chunk_index"] != entry["chunk_index"]
            or len(chunk["rows"]) != entry["row_count"]
            or not chunk["rows"]
        ):
            raise ValueError("R2 snapshot chunk header/row count mismatch: " + key)
        cursor = chunk["order_by"]
        if (
            chunk["rows"][0].get(cursor) != entry["first_key"]
            or chunk["rows"][-1].get(cursor) != entry["last_key"]
        ):
            raise ValueError("R2 snapshot cursor boundaries differ: " + key)
        if full:
            table = entry["table"]
            previous = last_key_by_table.get(table)
            first = chunk["rows"][0].get(cursor)
            if previous is not None and (first is None or first <= previous):
                raise ValueError("R2 snapshot cross-chunk cursor order invalid: " + table)
            last_key_by_table[table] = chunk["rows"][-1].get(cursor)
            verified_by_table[table] = verified_by_table.get(table, 0) + len(chunk["rows"])
        checked_rows += len(chunk["rows"])

    if full and (
        checked_rows != sum(int(count) for count in manifest["row_counts"].values())
        or any(verified_by_table.get(table, 0) != int(count)
               for table, count in manifest["row_counts"].items())
    ):
        raise ValueError("R2 full readback row counts do not agree with manifest")

    return {
        "readback_status": "ok",
        "readback_kind": (
            "FULL_LOGICAL_INTEGRITY_NOT_D1_RESTORE" if full
            else "SAMPLED_LOGICAL_INTEGRITY_NOT_FULL_RESTORE"
        ),
        "checked_chunks": len(selected),
        "checked_rows": checked_rows,
        "manifest_key": manifest_key,
    }
