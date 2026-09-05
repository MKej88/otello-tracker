from __future__ import annotations

from src.estimated_nav_history_cash_display import _restore_daily_chart_points


def test_history_chart_uses_every_validated_trading_day() -> None:
    statistics_points = [
        {
            "date": f"2026-01-{day:02d}",
            "nav_per_share": 30.0 + day,
            "otec_price": 20.0 + day,
            "discount_pct": 30.0,
        }
        for day in range(1, 21)
    ]
    result = {
        "ready": True,
        "observation_count": len(statistics_points),
        "chart_point_count": 5,
        "point_count": 5,
        "points": statistics_points[::4],
        "_statistics_points": statistics_points,
    }

    restored = _restore_daily_chart_points(result)

    assert restored["points"] == statistics_points
    assert restored["chart_point_count"] == len(statistics_points)
    assert restored["point_count"] == len(statistics_points)
