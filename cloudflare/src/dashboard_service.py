from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

CORE_CALCULATION_VERSION = "core-market-nav-daily-v1"
FULL_CALCULATION_VERSION = "full-market-nav-daily-v2"
RECENT_OWNERSHIP_MAX_AGE_DAYS = 180
STALE_MARKET_COMPONENT_DAYS = 4


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def _pct_change(current: Any, previous: Any) -> float | None:
    if current is None or previous is None:
        return None
    old = Decimal(str(previous))
    if old == 0:
        return None
    return float((Decimal(str(current)) / old - Decimal("1")) * Decimal("100"))


def _components(row: dict[str, Any] | None) -> dict[str, Any]:
    raw = row.get("components_json") if row is not None else None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


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


async def _latest_series_date(repository, calculation_version: str, nav_scope: str) -> str | None:
    row = await repository.first(
        """
        SELECT MAX(substr(as_of_at, 1, 10)) AS max_date
        FROM nav_snapshots
        WHERE calculation_version = ? AND nav_scope = ?
        """,
        (calculation_version, nav_scope),
    )
    return row.get("max_date") if row is not None else None


async def _preferred_nav_series(repository) -> tuple[str, str]:
    core_date = await _latest_series_date(repository, CORE_CALCULATION_VERSION, "CORE")
    full_date = await _latest_series_date(repository, FULL_CALCULATION_VERSION, "FULL")

    if full_date is not None and core_date == full_date:
        return FULL_CALCULATION_VERSION, "FULL"
    if core_date is not None:
        return CORE_CALCULATION_VERSION, "CORE"
    if full_date is not None:
        return FULL_CALCULATION_VERSION, "FULL"
    return CORE_CALCULATION_VERSION, "CORE"


async def _core_components_for_date(repository, as_of_at: str) -> dict[str, Any]:
    row = await repository.first(
        """
        SELECT components_json FROM nav_snapshots
        WHERE as_of_at = ? AND calculation_version = ? AND nav_scope = 'CORE'
        LIMIT 1
        """,
        (as_of_at, CORE_CALCULATION_VERSION),
    )
    return _components(row)


async def dashboard_summary(repository) -> dict[str, Any]:
    """D1 equivalent of the validated SQLite dashboard summary contract."""
    calculation_version, model_scope = await _preferred_nav_series(repository)
    rows = await repository.all(
        """
        SELECT as_of_at, nav_per_share_nok, otec_price_nok, discount_pct,
               bemobi_value_nok, cash_estimate_nok, other_net_assets_nok,
               shares_outstanding, status, components_json, quality_notes
        FROM nav_snapshots
        WHERE calculation_version = ? AND nav_scope = ?
        ORDER BY as_of_at DESC LIMIT 2
        """,
        (calculation_version, model_scope),
    )

    if not rows:
        return {
            "ready": False,
            "data_status": "not_ready",
            "model_scope": "CORE",
            "calculation_version": CORE_CALCULATION_VERSION,
            "message": "Kjør markedsdata-backfill og NAV-rebuild for å fylle dashboardet.",
        }

    latest = rows[0]
    previous = rows[1] if len(rows) > 1 else None
    if model_scope == "FULL":
        current_components = await _core_components_for_date(repository, latest["as_of_at"])
        previous_components = (
            await _core_components_for_date(repository, previous["as_of_at"])
            if previous is not None
            else {}
        )
    else:
        current_components = _components(latest)
        previous_components = _components(previous)

    bmob3 = current_components.get("bmob3", {})
    previous_bmob3 = previous_components.get("bmob3", {})
    cash = current_components.get("cash", {})
    otec = current_components.get("otec", {})

    as_of_date = str(latest["as_of_at"])[:10]
    holding = await repository.first(
        """
        SELECT shares, ownership_pct FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of_date, as_of_date),
    )
    latest_buyback = await repository.first(
        """
        SELECT trade_date, shares, avg_price_nok, amount_nok,
               treasury_shares_after, cumulative_program_shares,
               cumulative_program_amount_nok
        FROM buybacks ORDER BY trade_date DESC, id DESC LIMIT 1
        """
    )

    nav_change = _pct_change(
        latest["nav_per_share_nok"],
        previous["nav_per_share_nok"] if previous else None,
    )
    otec_change = _pct_change(
        latest["otec_price_nok"], previous["otec_price_nok"] if previous else None
    )
    discount_change = (
        float(Decimal(str(latest["discount_pct"])) - Decimal(str(previous["discount_pct"])))
        if previous is not None
        and latest["discount_pct"] is not None
        and previous["discount_pct"] is not None
        else None
    )
    bmob3_change = _pct_change(bmob3.get("price_brl"), previous_bmob3.get("price_brl"))
    brl_change = _pct_change(bmob3.get("brl_nok"), previous_bmob3.get("brl_nok"))
    cash_change = _pct_change(
        latest["cash_estimate_nok"], previous["cash_estimate_nok"] if previous else None
    )

    return {
        "ready": True,
        "data_status": latest["status"],
        "model_scope": model_scope,
        "calculation_version": calculation_version,
        "as_of_date": as_of_date,
        "nav_per_share": _float(latest["nav_per_share_nok"]),
        "otec_price": _float(latest["otec_price_nok"]),
        "nav_discount_pct": _float(latest["discount_pct"]),
        "bmob3_price": _float(bmob3.get("price_brl")),
        "brl_nok": _float(bmob3.get("brl_nok")),
        "estimated_cash_mnok": (
            _float(latest["cash_estimate_nok"]) / 1_000_000
            if latest["cash_estimate_nok"] is not None
            else None
        ),
        "other_net_assets_mnok": (
            _float(latest["other_net_assets_nok"]) / 1_000_000
            if latest["other_net_assets_nok"] is not None
            else None
        ),
        "bemobi_value_mnok": (
            _float(latest["bemobi_value_nok"]) / 1_000_000
            if latest["bemobi_value_nok"] is not None
            else None
        ),
        "bemobi_shares": int(holding["shares"]) if holding is not None else None,
        "bemobi_ownership_pct": _float(holding["ownership_pct"]) if holding is not None else None,
        "shares_outstanding": int(latest["shares_outstanding"]),
        "cash_quality": cash.get("quality"),
        "cash_calibration_quality": cash.get("calibration_quality"),
        "share_count_quality": otec.get("share_count_quality"),
        "otec_price_quality": otec.get("price_quality"),
        "otec_price_source": otec.get("price_source"),
        "bmob3_price_quality": bmob3.get("price_quality"),
        "bmob3_price_source": bmob3.get("price_source"),
        "quality_notes": latest["quality_notes"],
        "changes": {
            "nav_pct": nav_change,
            "otec_pct": otec_change,
            "discount_pp": discount_change,
            "bmob3_pct": bmob3_change,
            "brl_nok_pct": brl_change,
            "cash_pct": cash_change,
        },
        "latest_buyback": latest_buyback,
    }


async def enrich_dashboard_summary(summary: dict[str, Any], repository) -> dict[str, Any]:
    """D1 equivalent of the validated freshness/ownership presentation safeguards."""
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
    row = await repository.first(
        """
        SELECT components_json
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope='CORE'
          AND substr(as_of_at,1,10)=?
        ORDER BY as_of_at DESC, id DESC LIMIT 1
        """,
        (CORE_CALCULATION_VERSION, as_of_text),
    )
    components = _parse_components(row["components_json"] if row else None)

    holding = await repository.first(
        """
        SELECT shares, ownership_pct, effective_from
        FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of_text, as_of_text),
    )

    bmob3 = components.get("bmob3") or {}
    otec = components.get("otec") or {}
    component_dates = {
        "otec": _as_date(otec.get("price_date")),
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
            "date": otec.get("price_date"),
            "observed_at": otec.get("price_observed_at"),
            "price_type": otec.get("price_type"),
        },
        "bmob3": {
            "date": bmob3.get("price_date"),
            "observed_at": bmob3.get("price_observed_at"),
            "price_type": bmob3.get("price_type"),
        },
        "brl_nok": {"date": bmob3.get("brl_nok_date")},
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
        reported_pct = (
            float(holding["ownership_pct"]) if holding["ownership_pct"] is not None else None
        )
        quality = (
            "REPORTED_RECENT"
            if reported_pct is not None and ownership_age <= RECENT_OWNERSHIP_MAX_AGE_DAYS
            else "STALE_REPORTED"
        )
        enriched["bemobi_ownership_reported_pct"] = reported_pct
        enriched["bemobi_ownership_effective_from"] = holding["effective_from"]
        enriched["bemobi_ownership_quality"] = quality
        enriched["bemobi_ownership_pct"] = reported_pct if quality == "REPORTED_RECENT" else None

    return enriched


async def dashboard_history(
    repository,
    *,
    days: int = 365,
    max_points: int = 400,
) -> dict[str, Any]:
    """D1 equivalent of bounded NAV/OTEC/discount history."""
    days = max(7, min(int(days), 3650))
    max_points = max(50, min(int(max_points), 1000))

    calculation_version, model_scope = await _preferred_nav_series(repository)
    latest = await repository.first(
        """
        SELECT MAX(substr(as_of_at,1,10)) AS max_date FROM nav_snapshots
        WHERE calculation_version = ? AND nav_scope = ?
        """,
        (calculation_version, model_scope),
    )
    if latest is None or latest["max_date"] is None:
        return {
            "ready": False,
            "data_status": "not_ready",
            "model_scope": model_scope,
            "calculation_version": calculation_version,
            "points": [],
        }

    end_date = date.fromisoformat(latest["max_date"])
    start_date = end_date - timedelta(days=days - 1)
    rows = await repository.all(
        """
        SELECT substr(as_of_at,1,10) AS date, nav_per_share_nok,
               otec_price_nok, discount_pct, cash_estimate_nok,
               other_net_assets_nok, status
        FROM nav_snapshots
        WHERE calculation_version = ? AND nav_scope = ?
          AND substr(as_of_at,1,10) >= ? AND substr(as_of_at,1,10) <= ?
        ORDER BY as_of_at
        """,
        (
            calculation_version,
            model_scope,
            start_date.isoformat(),
            end_date.isoformat(),
        ),
    )

    raw = [
        {
            "date": row["date"],
            "nav_per_share": _float(row["nav_per_share_nok"]),
            "otec_price": _float(row["otec_price_nok"]),
            "discount_pct": _float(row["discount_pct"]),
            "cash_mnok": _float(row["cash_estimate_nok"]) / 1_000_000,
            "other_net_assets_mnok": _float(row["other_net_assets_nok"]) / 1_000_000,
            "status": row["status"],
        }
        for row in rows
    ]

    if len(raw) > max_points:
        step = (len(raw) - 1) / (max_points - 1)
        indices = sorted({round(index * step) for index in range(max_points)})
        points = [raw[index] for index in indices]
        if points[-1]["date"] != raw[-1]["date"]:
            points[-1] = raw[-1]
    else:
        points = raw

    discounts = [
        Decimal(str(item["discount_pct"]))
        for item in raw
        if item["discount_pct"] is not None
    ]
    average_discount = (
        float(sum(discounts, Decimal("0")) / Decimal(len(discounts))) if discounts else None
    )

    return {
        "ready": bool(points),
        "data_status": points[-1]["status"] if points else "not_ready",
        "model_scope": model_scope,
        "calculation_version": calculation_version,
        "from": points[0]["date"] if points else None,
        "to": points[-1]["date"] if points else None,
        "raw_count": len(raw),
        "point_count": len(points),
        "average_discount_pct": average_discount,
        "points": points,
    }
