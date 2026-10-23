"""Persist the expensive Brazil response independently of visitors' browser caches."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

STATE_KEY = "brazil_dashboard_snapshot_v1"
SGS_DIAGNOSTICS_STATE_KEY = "brazil_sgs_http_diagnostics_v1"
SGS_KEYS = ("selic", "ipca_12m", "ibc_br", "ibc_services")
# Only the following structured fields are persisted. Never store raw upstream bodies.
SGS_DIAGNOSTIC_FIELDS = (
    "error_kind", "http_status", "content_type", "response_bytes",
    "response_kind", "date", "last_success_at",
)
MAX_AGE_SECONDS = 90 * 60
PARTIAL_MAX_AGE_SECONDS = 35 * 60
# Stale-while-revalidate safety window: show clearly-labelled data, never wait on upstream.
MAX_STALE_AGE_SECONDS = 7 * 24 * 60 * 60
# Prefer a complete dataset for one day; then newer partial data may replace it.
COMPLETE_SNAPSHOT_PROTECTION_SECONDS = 24 * 60 * 60
REFRESH_TIMEOUT_SECONDS = 120


def snapshot_complete(payload: dict) -> bool:
    """ready means some data exists; it does not mean the investor view is complete."""
    metrics = payload.get("metrics") or {}
    if not isinstance(metrics, dict):
        return False
    if not all(
        isinstance(metrics.get(key), dict) and metrics[key].get("value") is not None
        for key in ("selic", "ipca_12m", "ibc_br", "ibc_services", "brl_nok")
    ):
        return False
    focus = payload.get("focus") or {}
    if not isinstance(focus, dict):
        return False
    values = focus.get("values") or {}
    try:
        year = int(payload["as_of_date"][:4])
        if not all(
            values.get(key, {}).get(str(y), {}).get("median") is not None
            for key in ("selic", "ipca", "gdp", "usd_brl")
            for y in (year, year + 1)
        ):
            return False
        comparison = (payload.get("focus_trend") or {}).get("comparisons", {}).get("30d", {})
        points = comparison.get("points_by_year") or {}
        return all(
            points.get(str(y), {}).get(key, {}).get("change") is not None
            for key in ("selic", "ipca", "gdp") for y in (year, year + 1)
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def snapshot_degraded(payload: dict) -> bool:
    statuses = payload.get("source_status") or {}
    return (
        bool(payload.get("snapshot_stale"))
        or not snapshot_complete(payload)
        or bool((payload.get("focus") or {}).get("fallback"))
        or any(isinstance(status, dict) and status.get("fallback") for status in statuses.values())
    )


async def build_dashboard(repository: Any, *, as_of_date: str | None = None) -> dict:
    # A snapshot hit must not import the external-source processing stack.
    try:
        from .brazil_dashboard_v2 import brazil_dashboard
    except ImportError:
        from brazil_dashboard_v2 import brazil_dashboard
    return await brazil_dashboard(repository, as_of_date=as_of_date)


async def load_snapshot(
    repository: Any, *, now: datetime | None = None, allow_stale: bool = False,
    diagnostics: dict[str, float | str] | None = None,
) -> dict | None:
    query_started = perf_counter()
    try:
        row = await repository.first(
            "SELECT value FROM runtime_state WHERE key = ?", (STATE_KEY,)
        )
    finally:
        if diagnostics is not None:
            diagnostics["d1_ms"] = round((perf_counter() - query_started) * 1000, 2)
    if not row:
        return None
    try:
        parse_started = perf_counter()
        try:
            payload = json.loads(row["value"])
        finally:
            if diagnostics is not None:
                diagnostics["parse_ms"] = round((perf_counter() - parse_started) * 1000, 2)
        if not isinstance(payload, dict) or not payload.get("ready"):
            return None
        generated = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        if generated.tzinfo is None:
            return None
        age = ((now or datetime.now(UTC)) - generated).total_seconds()
        max_age = PARTIAL_MAX_AGE_SECONDS if snapshot_degraded(payload) else MAX_AGE_SECONDS
        allowed_age = MAX_STALE_AGE_SECONDS if allow_stale else max_age
        if not 0 <= age <= allowed_age:
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if age > max_age:
        return {**payload, "snapshot_stale": True}
    return payload


async def save_snapshot(repository: Any, payload: dict) -> None:
    # An upstream outage must not overwrite a useful snapshot with an empty page.
    if not payload.get("ready") or not payload.get("generated_at"):
        return
    complete = snapshot_complete(payload)
    if not complete:
        row = await repository.first(
            "SELECT value FROM runtime_state WHERE key = ?", (STATE_KEY,)
        )
        try:
            previous = json.loads(row["value"]) if row else {}
            if isinstance(previous, dict) and snapshot_complete(previous):
                previous_at = datetime.fromisoformat(
                    str(previous["generated_at"]).replace("Z", "+00:00")
                )
                new_at = datetime.fromisoformat(
                    str(payload["generated_at"]).replace("Z", "+00:00")
                )
                delta = (new_at - previous_at).total_seconds()
                if 0 <= delta < COMPLETE_SNAPSHOT_PROTECTION_SECONDS:
                    return
        except (KeyError, TypeError, ValueError):
            pass
    stored = dict(payload, snapshot_complete=complete)
    await repository.run(
        """INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value, updated_at = excluded.updated_at
        WHERE julianday(excluded.updated_at) >= julianday(runtime_state.updated_at)
            AND (json_extract(excluded.value, '$.snapshot_complete') = 1
                OR COALESCE(json_extract(runtime_state.value, '$.snapshot_complete'), 0) = 0
                OR julianday(excluded.updated_at) - julianday(runtime_state.updated_at) >= 1)""",
        (STATE_KEY, json.dumps(stored, ensure_ascii=False, separators=(",", ":")),
         payload["generated_at"]),
    )


async def cached_brazil_dashboard(
    repository: Any, *, as_of_date: str | None = None,
    diagnostics: dict[str, float | str] | None = None,
) -> dict:
    # Explicit historical requests must neither read nor replace today's snapshot.
    if as_of_date is not None:
        if diagnostics is not None:
            diagnostics["snapshot"] = "historical"
        return await build_dashboard(repository, as_of_date=as_of_date)
    try:
        cached = await load_snapshot(repository, allow_stale=True, diagnostics=diagnostics)
    except Exception:
        cached = None
    if cached is not None:
        if diagnostics is not None:
            diagnostics["snapshot"] = "stale" if cached.get("snapshot_stale") else "fresh"
        return cached
    if diagnostics is not None:
        diagnostics["snapshot"] = "missing"

    # Visitor requests never fetch from BCB/Olinda/Investing.com. The scheduled
    # refresh job owns external source work; do not block the first visitor.
    return {
        "ready": False,
        "snapshot_unavailable": True,
        "source_status": {},
    }


async def save_sgs_diagnostics(repository: Any, payload: dict) -> None:
    """Always persist the last SGS attempt, even if a complete dashboard is protected."""
    generated_at = payload.get("generated_at")
    statuses = payload.get("source_status")
    if not generated_at or not isinstance(statuses, dict):
        return
    sources = {}
    for key in SGS_KEYS:
        status = statuses.get(key)
        if not isinstance(status, dict):
            continue
        # A fallback may be 'ready' on screen without a successful live fetch.
        sources[key] = {
            "live_ready": bool(status.get("live_ready", status.get("ready"))),
            **{field: status[field] for field in SGS_DIAGNOSTIC_FIELDS
               if status.get(field) is not None},
        }
    if not sources:
        return
    diagnostic = {
        "generated_at": generated_at,
        "as_of_date": payload.get("as_of_date"),
        "sources": sources,
    }
    await repository.run(
        """INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
          value = excluded.value,
          updated_at = excluded.updated_at
        WHERE julianday(excluded.updated_at) >= julianday(runtime_state.updated_at)""",
        (
            SGS_DIAGNOSTICS_STATE_KEY,
            json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")),
            generated_at,
        ),
    )


async def refresh_brazil_snapshot(repository: Any) -> dict:
    # Bound this optional cron step so unavailable sources cannot stall market refreshes.
    payload = await asyncio.wait_for(
        build_dashboard(repository), timeout=REFRESH_TIMEOUT_SECONDS
    )
    # Separate from the main snapshot: its 24-hour complete-snapshot protection
    # must never hide current HTTP diagnostics for failing SGS requests.
    try:
        await save_sgs_diagnostics(repository, payload)
    except Exception:
        pass  # Best effort, like the other optional dashboard cache writes.
    if not payload.get("ready"):
        return {"status": "error", "reason": "Brazil sources unavailable"}
    await save_snapshot(repository, payload)
    return {"status": "ok", "generated_at": payload.get("generated_at")}
