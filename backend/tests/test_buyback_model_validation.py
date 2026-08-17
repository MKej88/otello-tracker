from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.jobs.backtest_buyback_forecast import Activity
from app.jobs.backtest_buyback_model import (
    BASELINE_MODEL,
    MODELS,
    Model,
    PredictionRecord,
    Week,
    _capacity,
    _factor,
    load_full_activity,
    pick_model,
)


def _record(model: str, day: str, *, actual: float, predicted: float) -> PredictionRecord:
    return PredictionRecord(
        model=model,
        program_start="2026-01-01",
        period_start=day,
        period_end=day,
        actual=actual,
        predicted=predicted,
        capacity=100.0,
        utilization=actual / 100.0,
    )


def test_full_activity_keeps_validated_pre_euronext_supplement() -> None:
    activity = load_full_activity()
    by_day = {item.day: item for item in activity}
    assert activity[0].day == date(2024, 6, 20)
    assert by_day[date(2024, 7, 5)].volume == 0
    assert by_day[date(2024, 8, 19)].volume > 0


def test_capacity_matches_production_positive_volume_semantics() -> None:
    start = date(2026, 1, 1)
    activity: list[Activity] = []
    for offset in range(21):
        activity.append(
            Activity(
                day=start + timedelta(days=offset),
                close=Decimal("10"),
                volume=0 if offset == 5 else 1_000,
            )
        )
    week_start = start + timedelta(days=21)
    for offset in range(5):
        activity.append(
            Activity(
                day=week_start + timedelta(days=offset),
                close=Decimal("10"),
                volume=0 if offset == 2 else 1_000,
            )
        )

    week = Week(
        program_start="2026-01-01",
        period_start=week_start,
        period_end=week_start + timedelta(days=4),
        actual_shares=0,
        cumulative_shares=0,
        max_program_shares=10_000,
    )
    capacity = _capacity(activity, week, 10_000, "adv20")
    assert capacity == 1_000.0


def test_model_selection_does_not_use_rows_after_holdout_cutoff() -> None:
    histories: dict[str, list[PredictionRecord]] = {model.name: [] for model in MODELS}
    before_days = [f"2026-01-{day:02d}" for day in range(1, 7)]
    after_days = [f"2026-02-{day:02d}" for day in range(1, 7)]

    for name in histories:
        for day in before_days:
            predicted = 100.0 if name == BASELINE_MODEL else 150.0
            histories[name].append(_record(name, day, actual=100.0, predicted=predicted))
        for day in after_days:
            predicted = 200.0 if name == BASELINE_MODEL else 100.0
            histories[name].append(_record(name, day, actual=100.0, predicted=predicted))

    selected, detail = pick_model(histories, before="2026-02-01")
    assert selected == BASELINE_MODEL
    baseline = next(row for row in detail if row["model"] == BASELINE_MODEL)
    assert baseline["train_weeks"] == 6
    assert baseline["wmape_pct"] == 0.0


def test_production_cold_start_and_utilization_cap_match_forecast() -> None:
    production = next(model for model in MODELS if model.name == BASELINE_MODEL)
    history_cold_start = next(
        model for model in MODELS if model.name == "production_with_history_cold_start"
    )

    assert _factor(production, [0.75], [0.50, 0.60, 0.70]) == 1.0
    assert _factor(history_cold_start, [0.75], [0.50, 0.60, 0.70]) < 1.0

    high_utilization = Model("test", "adv20", "median8", "one")
    assert _factor(high_utilization, [1.30, 1.40], []) == 1.10
