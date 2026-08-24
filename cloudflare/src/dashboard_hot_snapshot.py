from __future__ import annotations

import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from fastapi.encoders import jsonable_encoder

# Keep the hot-snapshot read path intentionally light. These wrappers preserve the public
# module names used by tests, but only import the expensive calculators if a snapshot really
# has to be rebuilt. A normal first-page HIT therefore avoids importing the whole NAV stack.
async def dashboard_summary(repository: Any) -> dict[str, Any]:
    try:
        from .dashboard_service import dashboard_summary as implementation
    except ImportError:
        from dashboard_service import dashboard_summary as implementation
    return await implementation(repository)


async def enrich_dashboard_summary(summary: dict[str, Any], repository: Any) -> dict[str, Any]:
    try:
        from .dashboard_service import enrich_dashboard_summary as implementation
    except ImportError:
        from dashboard_service import enrich_dashboard_summary as implementation
    return await implementation(summary, repository)


async def economic_nav_summary(repository: Any) -> dict[str, Any]:
    try:
        from .economic_nav_investor import economic_nav_summary as implementation
    except ImportError:
        from economic_nav_investor import economic_nav_summary as implementation
    return await implementation(repository)


async def market_quote_details(repository: Any) -> dict[str, Any]:
    try:
        from .quote_details import market_quote_details as implementation
    except ImportError:
        from quote_details import market_quote_details as implementation
    return await implementation(repository)


async def buyback_forecast(repository: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        from .buyback_service import buyback_forecast as implementation
    except ImportError:
        from buyback_service import buyback_forecast as implementation
    return await implementation(repository, *args, **kwargs)


# Persisted hot snapshots contain already-rendered API payloads. Bump both the key
# and version whenever response semantics change so a newly deployed Worker cannot
# serve a payload produced by the previous application version.
STATE_KEY = "dashboard_hot_snapshot_v2"
SNAPSHOT_VERSION = 2
_COMPONENTS = {"summary", "economic", "quotes", "forecast"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def build_dashboard_hot_snapshot(repository: Any) -> dict[str, Any]:
    """Build the expensive first-screen payload outside the user request path."""
    summary = await dashboard_summary(repository)
    summary = await enrich_dashboard_summary(summary, repository)
    economic = await economic_nav_summary(repository)
    quotes = await market_quote_details(repository)
    forecast = await buyback_forecast(repository)
    generated_at = _now_iso()
    return jsonable_encoder(
        {
            "version": SNAPSHOT_VERSION,
            "generated_at": generated_at,
            "summary": summary,
            "economic": economic,
            "quotes": quotes,
            "forecast": forecast,
        }
    )


async def load_dashboard_hot_snapshot(repository: Any) -> dict[str, Any] | None:
    row = await repository.first(
        "SELECT value, updated_at FROM runtime_state WHERE key = ?",
        (STATE_KEY,),
    )
    if row is None:
        return None
    try:
        payload = json.loads(str(row.get("value") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != SNAPSHOT_VERSION:
        return None
    if not _COMPONENTS.issubset(payload):
        return None
    return payload


async def dashboard_bootstrap_payload(repository: Any) -> dict[str, Any]:
    """Return all first-screen components through one D1 snapshot read.

    A live calculation is kept only as a fail-safe for a missing/invalid snapshot.
    The response includes small timing metadata so cold-start vs application work can
    be distinguished in production without exposing investor internals.
    """
    started = perf_counter()
    snapshot = await load_dashboard_hot_snapshot(repository)
    source = "hot_snapshot"
    if snapshot is None:
        snapshot = await build_dashboard_hot_snapshot(repository)
        source = "live_fallback"

    return {
        "summary": snapshot["summary"],
        "economic": snapshot["economic"],
        "quotes": snapshot["quotes"],
        "forecast": snapshot["forecast"],
        "meta": {
            "source": source,
            "snapshot_version": snapshot.get("version"),
            "generated_at": snapshot.get("generated_at"),
            "server_ms": round((perf_counter() - started) * 1000, 2),
        },
    }


async def dashboard_hot_snapshot_status(
    repository: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Expose small, non-sensitive cache diagnostics without returning cached investor data."""
    row = await repository.first(
        "SELECT value, updated_at FROM runtime_state WHERE key = ?",
        (STATE_KEY,),
    )
    base = {
        "state_key": STATE_KEY,
        "expected_version": SNAPSHOT_VERSION,
        "available": row is not None,
        "valid": False,
        "cache_status": "MISS",
        "stored_version": None,
        "generated_at": None,
        "age_seconds": None,
        "bytes": 0,
        "components": [],
        "reason": "missing" if row is None else None,
    }
    if row is None:
        return base

    raw = str(row.get("value") or "")
    base["bytes"] = len(raw.encode("utf-8"))
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {**base, "reason": "invalid_json", "generated_at": row.get("updated_at")}

    if not isinstance(payload, dict):
        return {**base, "reason": "invalid_payload", "generated_at": row.get("updated_at")}

    stored_version = payload.get("version")
    generated_at = payload.get("generated_at") or row.get("updated_at")
    present_components = sorted(name for name in _COMPONENTS if isinstance(payload.get(name), dict))
    current = (now or datetime.now(UTC)).astimezone(UTC)
    generated = _parse_timestamp(generated_at)
    age_seconds = (
        max(0, int((current - generated).total_seconds()))
        if generated is not None
        else None
    )

    if stored_version != SNAPSHOT_VERSION:
        reason = "version_mismatch"
    elif len(present_components) != len(_COMPONENTS):
        reason = "missing_or_invalid_components"
    else:
        reason = None

    valid = reason is None
    return {
        **base,
        "valid": valid,
        "cache_status": "HIT" if valid else "MISS",
        "stored_version": stored_version,
        "generated_at": generated_at,
        "age_seconds": age_seconds,
        "components": present_components,
        "reason": reason,
    }


async def dashboard_hot_component(repository: Any, component: str) -> dict[str, Any] | None:
    """Return one cached API payload without changing its public response shape."""
    if component not in _COMPONENTS:
        raise ValueError(f"Unknown dashboard hot-snapshot component: {component}")
    payload = await load_dashboard_hot_snapshot(repository)
    if payload is None:
        return None
    value = payload.get(component)
    return value if isinstance(value, dict) else None


async def refresh_dashboard_hot_snapshot(
    repository: Any,
    *,
    force: bool = True,
) -> dict[str, Any]:
    """Refresh the persisted first-screen snapshot, or seed it if it does not exist."""
    if not force:
        existing = await load_dashboard_hot_snapshot(repository)
        if existing is not None:
            return {
                "status": "skipped",
                "reason": "inputs_unchanged",
                "generated_at": existing.get("generated_at"),
            }

    payload = await build_dashboard_hot_snapshot(repository)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    generated_at = str(payload["generated_at"])
    await repository.run(
        """
        INSERT INTO runtime_state(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (STATE_KEY, encoded, generated_at),
    )
    return {
        "status": "ok",
        "generated_at": generated_at,
        "bytes": len(encoded.encode("utf-8")),
        "components": sorted(_COMPONENTS),
    }
