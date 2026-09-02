from datetime import date, timedelta

import pytest

from app.marketdata.quote_details import _price_changes, _relative_volume


def _row(days_ago: int, price: float) -> dict[str, object]:
    return {
        "trading_date": (date(2026, 9, 1) - timedelta(days=days_ago)).isoformat(),
        "price": price,
    }


def test_price_changes_use_previous_and_nearest_observation_on_or_before() -> None:
    history = [_row(92, 80), _row(32, 90), _row(1, 100), _row(0, 110)]

    result = _price_changes(history, 110, "2026-09-01")

    assert result["daily_pct"] == pytest.approx(10)
    assert result["month_pct"] == pytest.approx(110 / 90 * 100 - 100)
    assert result["three_month_pct"] == pytest.approx(37.5)


def test_price_changes_are_missing_without_reference_history() -> None:
    result = _price_changes([_row(0, 110)], 110, "2026-09-01")

    assert result == {"daily_pct": None, "month_pct": None, "three_month_pct": None}


@pytest.mark.parametrize(
    ("volume", "expected"),
    [
        ({"latest": 120, "average_3m": 10, "average_sessions": 63}, 12),
        ({"latest": 120, "average_3m": 10, "average_sessions": 1}, None),
        ({"latest": 120, "average_3m": 0, "average_sessions": 63}, None),
        ({"latest": None, "average_3m": 10, "average_sessions": 63}, None),
    ],
)
def test_relative_volume_is_null_safe(
    volume: dict[str, float | int | None], expected: float | None
) -> None:
    assert _relative_volume(volume) == expected
