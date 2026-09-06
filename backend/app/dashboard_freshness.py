from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.db.connection import get_connection
from app.nav.daily_nav import CALCULATION_VERSION as CORE_CALCULATION_VERSION

RECENT_OWNERSHIP_MAX_AGE_DAYS = 180
STALE_MARKET_COMPONENT_DAYS = 4


def _parse_components(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def enrich_dashboard_summary(
    summary: dict[str, Any],
    database_path: str | None = None,
) -> dict[str, Any]:
    """Add timestamp compatibility and ownership-quality metadata to a dashboard snapshot."""
    enriched = dict(summary)
    if not summary.get("ready") or not summary.get("as_of_date"):
        enriched["market_timestamps"] = {
            "status": "UNKNOWN",
            "indicative": True,
            "reason": "dashboard_not_ready",
        }
        return enriched

    as_of_text = str(summary["as_of_date"])[:10]
    as_of = date.fromisoformat(as_of_text)
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT components_json
            FROM nav_snapshots
            WHERE calculation_version=? AND nav_scope='CORE'
              AND substr(as_of_at,1,10)=?
            ORDER BY as_of_at DESC, id DESC LIMIT 1
            """,
            (CORE_CALCULATION_VERSION, as_of_text),
        ).fetchone()
        components = _parse_components(row["components_json"] if row else None)

        holding = connection.execute(
            """
            SELECT shares, ownership_pct, effective_from
            FROM bemobi_holdings
            WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
            ORDER BY effective_from DESC, id DESC LIMIT 1
            """,
            (as_of_text, as_of_text),
        ).fetchone()

    bmob3 = components.get("bmob3") or {}
    otec = components.get("otec") or {}
    component_dates = {
        "otec": _as_date(summary.get("otec_price_date") or otec.get("price_date")),
        "bmob3": _as_date(bmob3.get("price_date")),
        "brl_nok": _as_date(bmob3.get("brl_nok_date")),
    }
    valid_dates = [item for item in component_dates.values() if item is not None]
    missing = [name for name, value in component_dates.items() if value is None]

    if missing or len(valid_dates) != 3:
        timestamp_status = "UNKNOWN"
        skew_days = None
        max_age = None
    else:
        skew_days = (max(valid_dates) - min(valid_dates)).days
        ages = [(as_of - item).days for item in valid_dates]
        max_age = max(ages)
        if max_age > STALE_MARKET_COMPONENT_DAYS:
            timestamp_status = "STALE"
        elif skew_days == 0:
            timestamp_status = "ALIGNED"
        else:
            timestamp_status = "MIXED"

    enriched["market_timestamps"] = {
        "status": timestamp_status,
        "indicative": timestamp_status != "ALIGNED",
        "as_of_date": as_of_text,
        "component_skew_days": skew_days,
        "max_component_age_days": max_age,
        "missing_components": missing,
        "otec": {
            "date": summary.get("otec_price_date") or otec.get("price_date"),
            "observed_at": (
                summary.get("otec_price_observed_at")
                or otec.get("price_observed_at")
            ),
            "price_type": summary.get("otec_price_type") or otec.get("price_type"),
        },
        "bmob3": {
            "date": bmob3.get("price_date"),
            "observed_at": bmob3.get("price_observed_at"),
            "price_type": bmob3.get("price_type"),
        },
        "brl_nok": {
            "date": bmob3.get("brl_nok_date"),
            "observed_at": bmob3.get("brl_nok_observed_at"),
            "source": bmob3.get("brl_nok_source"),
        },
        "note": (
            "MIXED means the NAV combines valid inputs from different market dates. "
            "This is common before Brazil/FX has caught up with a fresh Oslo trade and "
            "should be treated as indicative rather than a synchronized market snapshot."
        ),
    }

    if holding is None:
        enriched["bemobi_ownership_pct"] = None
        enriched["bemobi_ownership_reported_pct"] = None
        enriched["bemobi_ownership_effective_from"] = None
        enriched["bemobi_ownership_quality"] = "UNKNOWN"
    else:
        effective = date.fromisoformat(holding["effective_from"])
        ownership_age = max(0, (as_of - effective).days)
        reported_pct = float(holding["ownership_pct"]) if holding["ownership_pct"] is not None else None
        quality = (
            "REPORTED_RECENT"
            if reported_pct is not None and ownership_age <= RECENT_OWNERSHIP_MAX_AGE_DAYS
            else "STALE_REPORTED"
        )
        enriched["bemobi_ownership_reported_pct"] = reported_pct
        enriched["bemobi_ownership_effective_from"] = holding["effective_from"]
        enriched["bemobi_ownership_quality"] = quality
        # Do not expose an old reported percentage as a current ownership percentage.
        # NAV uses the explicit Bemobi share count, so this presentation safeguard has no
        # impact on valuation.
        enriched["bemobi_ownership_pct"] = reported_pct if quality == "REPORTED_RECENT" else None

    return enriched
