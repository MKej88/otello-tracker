"""Persist the expensive Brazil response independently of visitors' browser caches."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

STATE_KEY = "brazil_dashboard_snapshot_v1"
MAX_AGE_SECONDS = 90 * 60
PARTIAL_MAX_AGE_SECONDS = 5 * 60
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
        not snapshot_complete(payload)
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


async def load_snapshot(repository: Any, *, now: datetime | None = None) -> dict | None:
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key = ?", (STATE_KEY,)
    )
    if not row:
        return None
    try:
        payload = json.loads(row["value"])
        if not isinstance(payload, dict) or not payload.get("ready"):
            return None
        generated = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        if generated.tzinfo is None:
            return None
        age = ((now or datetime.now(UTC)) - generated).total_seconds()
        max_age = PARTIAL_MAX_AGE_SECONDS if snapshot_degraded(payload) else MAX_AGE_SECONDS
        if not 0 <= age <= max_age:
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
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
                OR COALESCE(json_extract(runtime_state.value, '$.snapshot_complete'), 0) = 0)""",
        (STATE_KEY, json.dumps(stored, ensure_ascii=False, separators=(",", ":")),
         payload["generated_at"]),
    )


async def cached_brazil_dashboard(repository: Any, *, as_of_date: str | None = None) -> dict:
    # Explicit historical requests must neither read nor replace today's snapshot.
    if as_of_date is not None:
        return await build_dashboard(repository, as_of_date=as_of_date)
    try:
        cached = await load_snapshot(repository)
    except Exception:
        cached = None
    if cached is not None:
        return cached
    payload = await build_dashboard(repository)
    try:
        await save_snapshot(repository, payload)
    except Exception:
        pass  # A cache write failure must not hide a successfully calculated response.
    return payload


async def refresh_brazil_snapshot(repository: Any) -> dict:
    # Bound this optional cron step so unavailable sources cannot stall market refreshes.
    payload = await asyncio.wait_for(
        build_dashboard(repository), timeout=REFRESH_TIMEOUT_SECONDS
    )
    if not payload.get("ready"):
        return {"status": "error", "reason": "Brazil sources unavailable"}
    await save_snapshot(repository, payload)
    return {"status": "ok", "generated_at": payload.get("generated_at")}
