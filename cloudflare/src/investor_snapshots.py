"""Persist current investor API payloads outside HTTP requests.

The existing 30-minute refresh owns these writes. A snapshot is an optimization
only: invalid, missing, expired, or cross-Oslo-date entries fall back to the
unchanged live endpoint implementation. Historical as-of requests never use it.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder

VERSION = 1
MAX_AGE_SECONDS = 40 * 60
KEYS = {
    "bemobi_dashboard": "investor_bemobi_dashboard_snapshot_v1",
    "bemobi_consensus": "investor_bemobi_consensus_snapshot_v1",
    "buybacks_dashboard": "investor_buybacks_dashboard_snapshot_v1",
}
OSLO_TZ = ZoneInfo("Europe/Oslo")


def _clock(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _oslo_date(now: datetime) -> str:
    return now.astimezone(OSLO_TZ).date().isoformat()


def _as_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def load_investor_snapshot(
    repository: Any, component: str, *, now: datetime | None = None
) -> dict[str, Any] | None:
    """One D1 row on a valid HTTP cache MISS, without changing public response JSON."""
    key = KEYS.get(component)
    if key is None:
        raise ValueError("Unknown investor snapshot component")
    row = await repository.first(
        "SELECT value, updated_at FROM runtime_state WHERE key = ?", (key,)
    )
    if row is None:
        return None
    try:
        item = json.loads(str(row.get("value") or ""))
    except (ValueError, TypeError):
        return None
    if not isinstance(item, dict) or item.get("version") != VERSION:
        return None
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return None
    clock = _clock(now)
    generated = _as_datetime(item.get("generated_at") or row.get("updated_at"))
    if generated is None:
        return None
    age = (clock - generated).total_seconds()
    if age < 0 or age > MAX_AGE_SECONDS:
        return None
    # This is especially important for the Oslo-date dependent buyback model.
    if item.get("oslo_date") != _oslo_date(clock):
        return None
    return payload


async def refresh_investor_snapshots(
    repository: Any, *, now: datetime | None = None
) -> dict[str, Any]:
    """Build after the fast/full ingestion steps, never in the visitor's request.

    Partial failure must not overwrite a valid previous snapshot. Its 40-minute
    expiry still guarantees the endpoint returns to the live calculation.
    """
    from bemobi_dashboard import bemobi_dashboard
    from bemobi_consensus_investor import bemobi_consensus
    from buyback_dashboard import buyback_dashboard

    clock = _clock(now)
    date_key = _oslo_date(clock)
    results: dict[str, Any] = {}
    cached_bemobi: dict[str, Any] | None = None

    for component in KEYS:
        try:
            if component == "bemobi_dashboard":
                payload = await bemobi_dashboard(repository)
                if isinstance(payload, dict) and payload.get("ready"):
                    cached_bemobi = payload
            elif component == "bemobi_consensus":
                payload = await bemobi_consensus(
                    repository, bemobi_payload=cached_bemobi
                )
            else:
                payload = await buyback_dashboard(repository, as_of_date=date_key)
            if not isinstance(payload, dict) or not payload.get("ready"):
                results[component] = {
                    "status": "skipped", "reason": "source_not_ready"
                }
                continue

            generated = _clock(now)
            encoded = json.dumps(
                jsonable_encoder({
                    "version": VERSION,
                    "oslo_date": date_key,
                    "generated_at": generated.isoformat(),
                    "payload": payload,
                }),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            await repository.run(
                """
                INSERT INTO runtime_state(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (KEYS[component], encoded, generated.isoformat()),
            )
            results[component] = {
                "status": "ok",
                "generated_at": generated.isoformat(),
                "bytes": len(encoded.encode("utf-8")),
            }
        except Exception as exc:
            # Do not turn a healthy refresh into an ingestion failure.
            results[component] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "non_critical": True,
            }

    return {
        "status": "partial" if any(
            row["status"] == "error" for row in results.values()
        ) else "ok",
        "components": results,
        "version": VERSION,
        "max_age_seconds": MAX_AGE_SECONDS,
    }
