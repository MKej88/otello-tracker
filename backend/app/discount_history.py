from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.dashboard import dashboard_history
from app.db.connection import get_connection
from app.economic_nav_investor import economic_nav_summary


def _float(value: Decimal | str | int | float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def _percentile(sorted_values: list[Decimal], quantile: Decimal) -> Decimal | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = Decimal(len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - Decimal(lower)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def _discount_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid: list[tuple[str, Decimal]] = []
    for row in rows:
        raw = row.get("discount_pct")
        if raw is None:
            continue
        valid.append((str(row.get("date") or ""), Decimal(str(raw))))

    if not valid:
        return {
            "count": 0,
            "current_discount_pct": None,
            "average_discount_pct": None,
            "median_discount_pct": None,
            "p10_discount_pct": None,
            "p25_discount_pct": None,
            "p75_discount_pct": None,
            "p90_discount_pct": None,
            "minimum_discount_pct": None,
            "minimum_discount_date": None,
            "maximum_discount_pct": None,
            "maximum_discount_date": None,
            "current_percentile": None,
            "premium_observation_count": 0,
        }

    values = sorted(value for _, value in valid)
    current = valid[-1][1]
    below = sum(1 for value in values if value < current)
    equal = sum(1 for value in values if value == current)
    current_percentile = (
        Decimal(below) + Decimal(equal) / Decimal("2")
    ) / Decimal(len(values)) * Decimal("100")
    minimum_date, minimum = min(valid, key=lambda item: (item[1], item[0]))
    maximum_date, maximum = max(valid, key=lambda item: (item[1], item[0]))

    return {
        "count": len(values),
        "current_discount_pct": _float(current),
        "average_discount_pct": _float(sum(values, Decimal("0")) / Decimal(len(values))),
        "median_discount_pct": _float(_percentile(values, Decimal("0.50"))),
        "p10_discount_pct": _float(_percentile(values, Decimal("0.10"))),
        "p25_discount_pct": _float(_percentile(values, Decimal("0.25"))),
        "p75_discount_pct": _float(_percentile(values, Decimal("0.75"))),
        "p90_discount_pct": _float(_percentile(values, Decimal("0.90"))),
        "minimum_discount_pct": _float(minimum),
        "minimum_discount_date": minimum_date,
        "maximum_discount_pct": _float(maximum),
        "maximum_discount_date": maximum_date,
        "current_percentile": _float(current_percentile),
        "premium_observation_count": sum(1 for value in values if value < 0),
    }


def _history_point(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": str(row["date"]),
        "nav_per_share": _float(row.get("nav_per_share_nok")),
        "otec_price": _float(row.get("otec_price_nok")),
        "discount_pct": _float(row.get("discount_pct")),
        "cash_mnok": None if row.get("cash_estimate_nok") is None else _float(row["cash_estimate_nok"]) / 1_000_000,
        "other_net_assets_mnok": None if row.get("other_net_assets_nok") is None else _float(row["other_net_assets_nok"]) / 1_000_000,
        "status": str(row.get("status") or "UNKNOWN"),
    }


def _downsample(points: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if len(points) <= max_points:
        return points
    indexes = sorted(
        {
            round(index * (len(points) - 1) / (max_points - 1))
            for index in range(max_points)
        }
    )
    return [points[index] for index in indexes]


def _economic_reference(database_path: str | None) -> dict[str, Any]:
    economic = economic_nav_summary(database_path)
    if not economic.get("ready"):
        return {
            "ready": False,
            "reason": economic.get("reason") or "economic_nav_not_ready",
            "as_of_date": economic.get("as_of_date"),
        }
    return {
        "ready": True,
        "as_of_date": economic.get("as_of_date"),
        "quality": economic.get("quality"),
        "nav_per_share": economic.get("nav_per_share"),
        "discount_pct": economic.get("discount_pct"),
        "conservative_nav_per_share": economic.get("conservative_nav_per_share"),
        "conservative_discount_pct": economic.get("conservative_discount_pct"),
    }


def discount_history(
    database_path: str | None = None,
    *,
    days: int = 365,
    max_points: int = 600,
) -> dict[str, Any]:
    """Historical validated NAV discount distribution plus current investor NAV reference.

    Statistics use the last complete validated NAV snapshot per calendar date so frequent
    intraday refreshes cannot overweight a day. Historical economic NAV is deliberately
    not reconstructed before its source-backed FX, cost and option inputs exist.
    """
    days = max(30, min(int(days), 3650))
    max_points = max(50, min(int(max_points), 1000))
    history = dashboard_history(database_path, days=days, max_points=max_points)
    if not history.get("ready"):
        return {
            **history,
            "period_days": days,
            "statistics": _discount_statistics([]),
            "current_economic": _economic_reference(database_path),
        }

    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT substr(as_of_at,1,10) AS date,
                       nav_per_share_nok, otec_price_nok, discount_pct,
                       cash_estimate_nok, other_net_assets_nok, status,
                       ROW_NUMBER() OVER (
                           PARTITION BY substr(as_of_at,1,10)
                           ORDER BY as_of_at DESC, id DESC
                       ) AS rn
                FROM nav_snapshots
                WHERE calculation_version=? AND nav_scope=?
                  AND substr(as_of_at,1,10) >= ? AND substr(as_of_at,1,10) <= ?
                  AND nav_per_share_nok IS NOT NULL
                  AND otec_price_nok IS NOT NULL
                  AND discount_pct IS NOT NULL
            )
            SELECT date, nav_per_share_nok, otec_price_nok, discount_pct,
                   cash_estimate_nok, other_net_assets_nok, status
            FROM ranked
            WHERE rn=1
            ORDER BY date
            """,
            (
                history["calculation_version"],
                history["model_scope"],
                history["from"],
                history["to"],
            ),
        ).fetchall()
        daily_rows = [dict(row) for row in rows]

    statistics = _discount_statistics(daily_rows)
    daily_points = [_history_point(row) for row in daily_rows]
    points = _downsample(daily_points, max_points)
    latest_point = daily_points[-1] if daily_points else None
    return {
        "ready": True,
        "data_status": history.get("data_status"),
        "period_days": days,
        "from": daily_points[0]["date"] if daily_points else history.get("from"),
        "to": daily_points[-1]["date"] if daily_points else history.get("to"),
        "raw_count": len(daily_points),
        "source_snapshot_count": history.get("raw_count"),
        "point_count": len(points),
        "basis": {
            "type": "VALIDATED_NAV_HISTORY",
            "model_scope": history.get("model_scope"),
            "calculation_version": history.get("calculation_version"),
            "observation_policy": "LATEST_COMPLETE_SNAPSHOT_PER_DATE",
            "note": (
                "Historiske persentiler bruker siste komplette validerte FULL/CORE NAV per dato. "
                "Dagens økonomiske investor-NAV vises separat; historiske økonomiske NAV-tall "
                "konstrueres ikke før kildebelagte valuta-, kostnads- og opsjonsinput finnes "
                "for perioden."
            ),
        },
        "statistics": statistics,
        "current_validated": (
            None
            if latest_point is None
            else {
                "date": latest_point.get("date"),
                "nav_per_share": latest_point.get("nav_per_share"),
                "otec_price": latest_point.get("otec_price"),
                "discount_pct": latest_point.get("discount_pct"),
            }
        ),
        "current_economic": _economic_reference(database_path),
        "points": points,
    }
