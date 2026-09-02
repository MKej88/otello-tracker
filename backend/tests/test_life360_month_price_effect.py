import pytest

from app.economic_nav_investor import _life360_month_price_effect


def _state(*, price: float, fx_rate: float, shares: int = 10) -> dict[str, object]:
    return {
        "ready": True,
        "price": price,
        "fx_rate": fx_rate,
        "shares": shares,
    }


def test_life360_month_effect_separates_price_from_currency() -> None:
    effect = _life360_month_price_effect(
        _state(price=10, fx_rate=10),
        _state(price=12, fx_rate=12),
        start_shares_outstanding=100,
        current_shares_outstanding=100,
    )

    assert effect == pytest.approx(2.2)


@pytest.mark.parametrize(
    ("start", "current", "start_outstanding", "current_outstanding"),
    [
        ({"ready": False}, _state(price=12, fx_rate=12), 100, 100),
        (_state(price=10, fx_rate=10), _state(price=12, fx_rate=12), 0, 100),
        (
            _state(price=10, fx_rate=10, shares=9),
            _state(price=12, fx_rate=12),
            100,
            100,
        ),
        (
            _state(price=float("nan"), fx_rate=10),
            _state(price=12, fx_rate=12),
            100,
            100,
        ),
    ],
)
def test_life360_month_effect_fails_closed_without_comparable_inputs(
    start: dict[str, object],
    current: dict[str, object],
    start_outstanding: int,
    current_outstanding: int,
) -> None:
    assert (
        _life360_month_price_effect(
            start,
            current,
            start_outstanding,
            current_outstanding,
        )
        is None
    )
