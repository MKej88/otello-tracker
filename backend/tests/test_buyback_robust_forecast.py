from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from app.buybacks.forecast_model import (
    model_confidence,
    point_estimate,
    uncertainty_band,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloudflare"))
from src.buyback_service import ProgramWeek, _history_metrics, _program_history  # noqa: E402


def september_replay():
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/buyback_forecast_september_2026.json"
        ).read_text()
    )
    path = ROOT / "backend/app/buybacks/data/otec_euronext_daily_activity_2024_2026.csv"
    with path.open() as handle:
        activity = {
            row["date"]: {
                "trading_date": row["date"],
                "volume_shares": int(row["volume_shares"]),
            }
            for row in csv.DictReader(handle)
        }
    activity.update({row["trading_date"]: row for row in fixture["activity_overlay"]})
    cumulative = 0
    weeks = []
    for row in fixture["weeks"]:
        cumulative += row["actual_shares"]
        weeks.append(
            ProgramWeek(
                date.fromisoformat(row["period_start"]),
                date.fromisoformat(row["period_end"]),
                row["actual_shares"],
                cumulative,
            )
        )
    # Match the production query's positive-volume observations.
    return weeks, sorted(
        [row for row in activity.values() if row["volume_shares"] > 0],
        key=lambda row: row["trading_date"],
    )


def test_september_regression_on_identical_inputs():
    weeks, activity = september_replay()
    history = _program_history(weeks, 2_192_046, activity)
    legacy = [
        {
            **row,
            "absolute_error_shares": abs(
                row["legacy_prediction_shares"] - row["actual_shares"]
            ),
        }
        for row in history
    ]
    assert len(history) == 16
    assert _history_metrics(legacy)["wmape_pct"] == pytest.approx(23.59, abs=0.02)
    assert _history_metrics(history)["wmape_pct"] < 11
    assert history[-1]["walk_forward_prediction_shares"] == pytest.approx(38_478, abs=1)
    assert history[-1]["adv20_shares"] == 74_335.3
    assert history[-1]["forecast_adv20_shares"] < 45_000
    # No retrospective deletion of the old misses from the captured live response.
    assert history[-1]["legacy_prediction_shares"] > 80_000


def test_future_volume_and_future_outcomes_cannot_change_earlier_predictions():
    weeks, activity = september_replay()
    before = _program_history(weeks, 2_192_046, activity)
    cutoff = date(2026, 9, 7)
    changed_activity = [
        {**row, "volume_shares": 9_000_000}
        if row["trading_date"] >= cutoff.isoformat()
        else row
        for row in activity
    ]
    changed_weeks = [
        ProgramWeek(w.period_start, w.period_end, 1, w.cumulative_shares)
        if w.period_start >= cutoff
        else w
        for w in weeks
    ]
    after = _program_history(changed_weeks, 2_192_046, changed_activity)
    for old, new in zip(before, after):
        if old["period_start"] <= cutoff.isoformat():
            assert (
                new["walk_forward_prediction_shares"]
                == old["walk_forward_prediction_shares"]
            )


def test_missing_target_week_volume_does_not_shorten_calendar_week():
    weeks, activity = september_replay()
    baseline = _program_history(weeks, 2_192_046, activity)
    cutoff = "2026-08-24"
    truncated = [row for row in activity if row["trading_date"] < cutoff]
    row = next(
        row
        for row in _program_history(weeks[:12], 2_192_046, truncated)
        if row["period_start"] == cutoff
    )
    expected = next(row for row in baseline if row["period_start"] == cutoff)
    assert row["trading_days"] == 5
    assert (
        row["walk_forward_prediction_shares"]
        == expected["walk_forward_prediction_shares"]
    )


def test_late_report_is_not_used_before_its_publication():
    weeks, activity = september_replay()
    last = weeks[-2]
    weeks[-2] = ProgramWeek(
        last.period_start, last.period_end, 1, 900_000, date(2026, 9, 22)
    )
    first = _program_history(weeks, 2_192_046, activity)[-1]
    weeks[-2] = ProgramWeek(
        last.period_start, last.period_end, 800_000, 1_900_000, date(2026, 9, 22)
    )
    second = _program_history(weeks, 2_192_046, activity)[-1]
    assert (
        first["walk_forward_prediction_shares"]
        == second["walk_forward_prediction_shares"]
    )


def test_outlier_damping_preserves_raw_volumes_and_mandate():
    lookback = [{"volume_shares": 40_000} for _ in range(19)] + [
        {"volume_shares": 800_000}
    ]
    point = point_estimate(lookback, 5, 2_000_000, [])
    assert point["adv20_shares"] == 78_000
    assert point["forecast_adv20_shares"] == 44_000
    assert point["volume_outlier_days"] == 1
    assert lookback[-1]["volume_shares"] == 800_000
    limited = point_estimate(lookback, 5, 500, [])
    assert limited["walk_forward_prediction_shares"] == 500


def test_recent_misses_widen_range_and_prevent_high_confidence():
    quiet = [
        {
            "actual_shares": 50_000,
            "absolute_error_shares": 1_000,
            "forecast_capacity_estimate_shares": 50_000,
        }
        for _ in range(8)
    ]
    misses = quiet[:5] + [
        {**row, "absolute_error_shares": 50_000} for row in quiet[-3:]
    ]
    assert model_confidence(quiet, "OPEN", 0) == "HIGH"
    assert model_confidence(misses, "OPEN", 0) == "LOW"
    assert model_confidence(quiet, "OPEN", 40) != "HIGH"
    assert uncertainty_band(misses) > uncertainty_band(quiet)


def test_model_mirror_has_no_drift():
    assert (ROOT / "backend/app/buybacks/forecast_model.py").read_text() == (
        ROOT / "cloudflare/src/buyback_model.py"
    ).read_text()
