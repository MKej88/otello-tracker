from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any

SNAPSHOT_VERSION = "d1-logical-snapshot-v1"
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024

# Static table names/order clauses keep the snapshot portable and avoid dynamic SQL input.
_SNAPSHOT_TABLES: tuple[tuple[str, str], ...] = (
    ("sources", "id"),
    ("instruments", "id"),
    ("source_documents", "id"),
    ("company_news", "id"),
    ("market_prices", "id"),
    ("market_activity", "id"),
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
    ("runtime_state", "key"),
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


async def build_d1_snapshot(repository, *, target_date: str) -> dict[str, Any]:
    tables: dict[str, list[dict[str, Any]]] = {}
    row_counts: dict[str, int] = {}
    for table, order_by in _SNAPSHOT_TABLES:
        rows = await repository.all(f"SELECT * FROM {table} ORDER BY {order_by}")
        tables[table] = rows
        row_counts[table] = len(rows)

    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "target_date": target_date,
        "tables": tables,
    }
    raw = _canonical_json(payload)
    logical_sha256 = hashlib.sha256(raw).hexdigest()
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    if len(compressed) > MAX_SNAPSHOT_BYTES:
        raise ValueError(
            f"D1 logical snapshot overstiger {MAX_SNAPSHOT_BYTES} bytes etter gzip"
        )
    return {
        "payload": compressed,
        "logical_sha256": logical_sha256,
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "uncompressed_bytes": len(raw),
        "compressed_bytes": len(compressed),
        "row_counts": row_counts,
        "table_count": len(_SNAPSHOT_TABLES),
    }


async def archive_d1_snapshot(
    repository,
    bucket,
    *,
    target_date: str,
    preflight_status: str | None = None,
) -> dict[str, Any]:
    built = await build_d1_snapshot(repository, target_date=target_date)
    digest = built["logical_sha256"]
    snapshot_key = f"snapshots/d1/{target_date}/logical-{digest[:20]}.json.gz"
    manifest_key = f"snapshots/d1/{target_date}/manifest-{digest[:20]}.json"
    await bucket.put(snapshot_key, built["payload"])

    manifest = {
        "snapshot_version": SNAPSHOT_VERSION,
        "target_date": target_date,
        "snapshot_key": snapshot_key,
        "logical_sha256": digest,
        "compressed_sha256": built["compressed_sha256"],
        "uncompressed_bytes": built["uncompressed_bytes"],
        "compressed_bytes": built["compressed_bytes"],
        "table_count": built["table_count"],
        "row_counts": built["row_counts"],
        "preflight_status": preflight_status,
        "restore_scope": "LOGICAL_AUDIT_SNAPSHOT_NOT_D1_TIME_TRAVEL_REPLACEMENT",
    }
    await bucket.put(manifest_key, _canonical_json(manifest))
    return {
        "status": "ok",
        **manifest,
        "manifest_key": manifest_key,
    }
