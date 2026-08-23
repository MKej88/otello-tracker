from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder

try:
    from .buyback_service import buyback_forecast
    from .dashboard_service import dashboard_summary, enrich_dashboard_summary
    from .economic_nav_investor import economic_nav_summary
    from .quote_details import market_quote_details
except ImportError:
    from buyback_service import buyback_forecast
    from dashboard_service import dashboard_summary, enrich_dashboard_summary
    from economic_nav_investor import economic_nav_summary
    from quote_details import market_quote_details

STATE_KEY = "dashboard_hot_snapshot_v1"
SNAPSHOT_VERSION = 1
_COMPONENTS = {"summary", "economic", "quotes", "forecast"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
