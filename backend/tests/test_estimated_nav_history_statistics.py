from __future__ import annotations

import asyncio
from pathlib import Path

import app.discount_history as backend_history
import src.discount_history as worker_history


def _history_result() -> dict:
    points = [
        {
            "date": f"2026-01-{index + 1:03d}",
            "discount_pct": float(index),
        }
        for index in range(200)
    ]
    points[73]["discount_pct"] = 1000.0
    chart_points = [*points[:71], points[-1]]
    return {
        "ready": True,
        "points": chart_points,
        "_statistics_points": points,
        "observation_count": 200,
        "chart_point_count": len(chart_points),
        "point_count": len(chart_points),
        "change": {"ready": False},
    }


def _assert_full_statistics(result: dict) -> None:
    expected = backend_history._discount_statistics(
        _history_result()["_statistics_points"]
    )

    assert result["observation_count"] == 200
    assert result["chart_point_count"] == 72
    assert len(result["points"]) == 72
    assert result["statistics"] == expected
    assert result["statistics"]["count"] == 200
    assert result["statistics"]["average_discount_pct"] == 104.135
    assert result["statistics"]["p10_discount_pct"] == 19.9
    assert result["statistics"]["median_discount_pct"] == 100.5
    assert result["statistics"]["p90_discount_pct"] == 180.1
    assert result["statistics"]["current_percentile"] == 99.25
    assert result["statistics"]["minimum_discount_pct"] == 0.0
    assert result["statistics"]["minimum_discount_date"] == "2026-01-001"
    assert result["statistics"]["maximum_discount_pct"] == 1000.0
    assert result["statistics"]["maximum_discount_date"] == "2026-01-074"
    assert "_statistics_points" not in result


def test_backend_statistics_use_every_valid_observation(monkeypatch) -> None:
    monkeypatch.setattr(
        backend_history,
        "estimated_nav_history",
        lambda *args, **kwargs: _history_result(),
    )

    result = backend_history._estimated_extension(None, 365)

    _assert_full_statistics(result)


def test_worker_statistics_match_backend_for_full_series(monkeypatch) -> None:
    async def history(*args, **kwargs):
        return _history_result()

    monkeypatch.setattr(worker_history, "estimated_nav_history", history)

    result = asyncio.run(worker_history._estimated_extension(object(), 365))

    _assert_full_statistics(result)


def test_frontend_labels_full_observation_count() -> None:
    source = Path(__file__).parents[2] / "frontend/src/EstimatedHistoryPage.tsx"
    page = source.read_text(encoding="utf-8")

    assert "data.observation_count ?? stats.count" in page
    assert "dagsobservasjoner" in page
