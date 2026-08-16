from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.nav.daily_nav import CALCULATION_VERSION as CORE_CALCULATION_VERSION
from app.nav.full_nav import FULL_CALCULATION_VERSION


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


def _components(row) -> dict[str, Any]:
    raw = row["components_json"] if row is not None else None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _preferred_nav_series(connection) -> tuple[str, str]:
    full = connection.execute(
        "SELECT 1 FROM nav_snapshots WHERE calculation_version = ? AND nav_scope = 'FULL' LIMIT 1",
        (FULL_CALCULATION_VERSION,),
    ).fetchone()
    if full is not None:
        return FULL_CALCULATION_VERSION, "FULL"
    return CORE_CALCULATION_VERSION, "CORE"


def _core_components_for_date(connection, as_of_at: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT components_json FROM nav_snapshots
        WHERE as_of_at = ? AND calculation_version = ? AND nav_scope = 'CORE'
        LIMIT 1
        """,
        (as_of_at, CORE_CALCULATION_VERSION),
    ).fetchone()
    return _components(row)


def dashboard_summary(database_path: str | None = None) -> dict[str, Any]:
    """Return latest real KPIs, preferring FULL NAV and safely falling back to CORE."""
    with get_connection(database_path) as connection:
        calculation_version, model_scope = _preferred_nav_series(connection)
        rows = connection.execute(
            """
            SELECT as_of_at, nav_per_share_nok, otec_price_nok, discount_pct,
                   bemobi_value_nok, cash_estimate_nok, other_net_assets_nok,
                   shares_outstanding, status, components_json, quality_notes
            FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = ?
            ORDER BY as_of_at DESC LIMIT 2
            """,
            (calculation_version, model_scope),
        ).fetchall()

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
            current_components = _core_components_for_date(connection, latest["as_of_at"])
            previous_components = (
                _core_components_for_date(connection, previous["as_of_at"])
                if previous is not None else {}
            )
        else:
            current_components = _components(latest)
            previous_components = _components(previous)

        bmob3 = current_components.get("bmob3", {})
        previous_bmob3 = previous_components.get("bmob3", {})
        cash = current_components.get("cash", {})
        otec = current_components.get("otec", {})

        as_of_date = str(latest["as_of_at"])[:10]
        holding = connection.execute(
            """
            SELECT shares, ownership_pct FROM bemobi_holdings
            WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
            ORDER BY effective_from DESC, id DESC LIMIT 1
            """,
            (as_of_date, as_of_date),
        ).fetchone()
        latest_buyback = connection.execute(
            """
            SELECT trade_date, shares, avg_price_nok, amount_nok,
                   treasury_shares_after, cumulative_program_shares,
                   cumulative_program_amount_nok
            FROM buybacks ORDER BY trade_date DESC, id DESC LIMIT 1
            """
        ).fetchone()

        nav_change = _pct_change(latest["nav_per_share_nok"], previous["nav_per_share_nok"] if previous else None)
        otec_change = _pct_change(latest["otec_price_nok"], previous["otec_price_nok"] if previous else None)
        discount_change = (
            float(Decimal(str(latest["discount_pct"])) - Decimal(str(previous["discount_pct"])))
            if previous is not None and latest["discount_pct"] is not None and previous["discount_pct"] is not None
            else None
        )
        bmob3_change = _pct_change(bmob3.get("price_brl"), previous_bmob3.get("price_brl"))
        brl_change = _pct_change(bmob3.get("brl_nok"), previous_bmob3.get("brl_nok"))
        cash_change = _pct_change(latest["cash_estimate_nok"], previous["cash_estimate_nok"] if previous else None)

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
            "estimated_cash_mnok": _float(latest["cash_estimate_nok"]) / 1_000_000 if latest["cash_estimate_nok"] is not None else None,
            "other_net_assets_mnok": _float(latest["other_net_assets_nok"]) / 1_000_000 if latest["other_net_assets_nok"] is not None else None,
            "bemobi_value_mnok": _float(latest["bemobi_value_nok"]) / 1_000_000 if latest["bemobi_value_nok"] is not None else None,
            "bemobi_shares": int(holding["shares"]) if holding is not None else None,
            "bemobi_ownership_pct": _float(holding["ownership_pct"]) if holding is not None else None,
            "shares_outstanding": int(latest["shares_outstanding"]),
            "cash_quality": cash.get("quality"),
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
            "latest_buyback": dict(latest_buyback) if latest_buyback is not None else None,
        }


def dashboard_history(
    database_path: str | None = None,
    *,
    days: int = 365,
    max_points: int = 400,
) -> dict[str, Any]:
    """Return bounded NAV/OTEC/discount history, preferring FULL where available."""
    days = max(7, min(int(days), 3650))
    max_points = max(50, min(int(max_points), 1000))

    with get_connection(database_path) as connection:
        calculation_version, model_scope = _preferred_nav_series(connection)
        latest = connection.execute(
            """
            SELECT MAX(substr(as_of_at,1,10)) AS max_date FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = ?
            """,
            (calculation_version, model_scope),
        ).fetchone()
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
        rows = connection.execute(
            """
            SELECT substr(as_of_at,1,10) AS date, nav_per_share_nok,
                   otec_price_nok, discount_pct, cash_estimate_nok,
                   other_net_assets_nok, status
            FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = ?
              AND substr(as_of_at,1,10) >= ? AND substr(as_of_at,1,10) <= ?
            ORDER BY as_of_at
            """,
            (calculation_version, model_scope, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()

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
        indices = sorted({round(i * step) for i in range(max_points)})
        points = [raw[index] for index in indices]
        if points[-1]["date"] != raw[-1]["date"]:
            points[-1] = raw[-1]
    else:
        points = raw

    discounts = [Decimal(str(item["discount_pct"])) for item in raw if item["discount_pct"] is not None]
    average_discount = float(sum(discounts, Decimal("0")) / Decimal(len(discounts))) if discounts else None

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
