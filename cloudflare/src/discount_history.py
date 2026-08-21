from __future__ import annotations

from decimal import Decimal
from typing import Any

from dashboard_service import dashboard_history
from economic_nav_investor import economic_nav_summary


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


async def _economic_reference(repository) -> dict[str, Any]:
    economic = await economic_nav_summary(repository)
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


async def discount_history(
    repository,
    *,
    days: int = 365,
    max_points: int = 600,
) -> dict[str, Any]:
    """Historical validated NAV discount distribution plus current investor NAV reference."""
    days = max(30, min(int(days), 3650))
    max_points = max(50, min(int(max_points), 1000))
    history = await dashboard_history(repository, days=days, max_points=max_points)
    if not history.get("ready"):
        return {
            **history,
            "period_days": days,
            "statistics": _discount_statistics([]),
            "current_economic": await _economic_reference(repository),
        }

    rows = await repository.all(
        """
        SELECT substr(as_of_at,1,10) AS date, discount_pct
        FROM nav_snapshots
        WHERE calculation_version=? AND nav_scope=?
          AND substr(as_of_at,1,10) >= ? AND substr(as_of_at,1,10) <= ?
        ORDER BY as_of_at
        """,
        (
            history["calculation_version"],
            history["model_scope"],
            history["from"],
            history["to"],
        ),
    )
    statistics = _discount_statistics(rows)
    latest_point = history["points"][-1] if history.get("points") else None
    return {
        "ready": True,
        "data_status": history.get("data_status"),
        "period_days": days,
        "from": history.get("from"),
        "to": history.get("to"),
        "raw_count": history.get("raw_count"),
        "point_count": history.get("point_count"),
        "basis": {
            "type": "VALIDATED_NAV_HISTORY",
            "model_scope": history.get("model_scope"),
            "calculation_version": history.get("calculation_version"),
            "note": (
                "Historiske persentiler bruker validert FULL/CORE NAV. Dagens økonomiske "
                "investor-NAV vises separat; historiske økonomiske NAV-tall konstrueres ikke "
                "før kildebelagte valuta-, kostnads- og opsjonsinput finnes for perioden."
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
        "current_economic": await _economic_reference(repository),
        "points": history.get("points") or [],
    }
