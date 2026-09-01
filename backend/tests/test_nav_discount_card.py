import math
from pathlib import Path

import pytest

from app.dashboard import nav_discount_metrics

ROOT = Path(__file__).resolve().parents[2]


def metrics(**overrides):
    inputs = {
        "nav_per_share": 14.85,
        "share_price": 11.35,
        "current_date": "2026-08-31",
        "observations": [
            {"date": "2025-08-31", "discount_pct": 40},
            {"date": "2026-07-30", "discount_pct": 30},
        ],
    }
    inputs.update(overrides)
    return nav_discount_metrics(**inputs)


def test_discount_and_upside_are_distinct_and_mathematically_consistent() -> None:
    result = metrics()

    assert result["discount_pct"] == pytest.approx((1 - 11.35 / 14.85) * 100)
    assert result["upside_to_nav_pct"] == pytest.approx((14.85 / 11.35 - 1) * 100)
    assert result["discount_pct"] != pytest.approx(result["upside_to_nav_pct"])
    assert result["month_change_pp"] == pytest.approx(result["discount_pct"] - 30)
    assert result["month_reference_date"] == "2026-07-30"


@pytest.mark.parametrize(
    ("values", "expected"),
    [([10, 20, 30], 20), ([10, 20, 30, 40], 25)],
)
def test_one_year_median_handles_odd_and_even_counts(values, expected) -> None:
    observations = [
        {"date": f"2026-08-{index + 1:02d}", "discount_pct": value}
        for index, value in enumerate(values)
    ]
    assert metrics(observations=observations)["median_1y_pct"] == expected


def test_range_position_is_clamped_by_the_view_and_flat_range_is_centered() -> None:
    result = metrics(
        nav_per_share=10,
        share_price=8,
        observations=[
            {"date": "2026-08-01", "discount_pct": 10},
            {"date": "2026-08-02", "discount_pct": 30},
        ],
    )
    assert result["range_1y"]["low"] == 10
    assert result["range_1y"]["high"] == 30
    assert result["range_1y"]["position_pct"] == pytest.approx(50)

    flat = metrics(observations=[{"date": "2026-08-01", "discount_pct": 20}])
    assert flat["range_1y"] == {"low": 20, "high": 20, "position_pct": 50}
    outside = metrics(nav_per_share=10, share_price=5)
    assert outside["range_1y"]["position_pct"] > 100
    assert metrics(observations=[])["range_1y"] == {
        "low": None,
        "high": None,
        "position_pct": None,
    }


@pytest.mark.parametrize(
    "bad_value",
    [None, math.nan, math.inf, -math.inf],
)
def test_invalid_observations_are_ignored(bad_value) -> None:
    result = metrics(
        observations=[
            {"date": "2026-08-01", "discount_pct": bad_value},
            {"date": "2026-08-02"},
            {"date": "2026-08-03", "discount_pct": 12},
        ]
    )
    assert result["median_1y_pct"] == 12


@pytest.mark.parametrize(
    ("nav", "price"),
    [
        (None, 10),
        (10, None),
        (0, 10),
        (-1, 10),
        (10, 0),
        (math.nan, 10),
        (10, math.inf),
    ],
)
def test_invalid_current_values_return_missing_metrics(nav, price) -> None:
    result = metrics(nav_per_share=nav, share_price=price, observations=[])
    assert result["discount_pct"] is None
    assert result["upside_to_nav_pct"] is None
    assert result["nav_per_share"] == (
        nav if nav is not None and math.isfinite(nav) and nav > 0 else None
    )
    assert result["share_price"] == (
        price if price is not None and math.isfinite(price) and price > 0 else None
    )


def test_frontend_renders_all_labels_and_safe_fallbacks() -> None:
    page = (ROOT / "frontend/src/OverviewPage.tsx").read_text(encoding="utf-8")
    for label in (
        "NAV / aksje",
        "Aksjekurs",
        "Oppside til NAV",
        "1 mnd",
        "1 år median",
        "Dagens rabatt i ettårsintervallet",
    ):
        assert label in page
    assert 'return "—"' in page
    assert "Number.isFinite(position)" in page
    assert "Math.max(0, Math.min(100, position))" in page
    assert "history?.estimated?.statistics" in page
    assert "nav?.discount_pct" in page
    assert "nav?.nav_per_share" in page
    assert "-discount.month_change_pp" in page
    assert "NaN" not in page
    assert "Infinity" not in page
