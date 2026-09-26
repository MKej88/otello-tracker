"""Reproducible v1/v2 replay using unchanged source observations.

Run from backend: PYTHONPATH=. python -m app.jobs.backtest_buyback_robust
No network calls, production writes, or parameter search.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.buybacks.forecast import _history_metrics
from app.buybacks.forecast_model import point_estimate
from app.buybacks.official_backfill import seed_known_official_buybacks
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.jobs.backtest_buyback_forecast import Activity
from app.jobs.backtest_buyback_model import Week, _actual_weeks, load_full_activity
from app.marketdata.oslo_calendar import oslo_bors_trading_days


def replay(activity: list[Activity], weeks: list[Week]) -> list[dict]:
    histories: dict[str, list[dict]] = {}
    cumulative: dict[str, int] = {}
    output = []
    for week in weeks:
        lookback = [
            row for row in activity if row.day < week.period_start and row.volume > 0
        ][-20:]
        if len(lookback) != 20:
            continue
        history = histories.setdefault(week.program_start, [])
        days = len(oslo_bors_trading_days(week.period_start, week.period_end))
        remaining = max(
            0, week.max_program_shares - cumulative.get(week.program_start, 0)
        )
        point = point_estimate(
            [{"volume_shares": row.volume} for row in lookback],
            days,
            remaining,
            history,
        )
        raw_capacity = point["week_start_capacity_estimate_shares"]
        model_capacity = point["forecast_capacity_estimate_shares"]
        row = {
            **point,
            "period_start": week.period_start.isoformat(),
            "period_end": week.period_end.isoformat(),
            "actual_shares": week.actual_shares,
            "utilization": week.actual_shares / raw_capacity if raw_capacity else 0,
            "forecast_utilization": week.actual_shares / model_capacity
            if model_capacity
            else 0,
            "absolute_error_shares": abs(
                point["walk_forward_prediction_shares"] - week.actual_shares
            ),
        }
        history.append(row)
        output.append(row)
        cumulative[week.program_start] = week.cumulative_shares
    return output


def comparison(rows: list[dict]) -> dict:
    legacy = [
        {
            **row,
            "absolute_error_shares": abs(
                row["legacy_prediction_shares"] - row["actual_shares"]
            ),
        }
        for row in rows
    ]
    return {"legacy": _history_metrics(legacy), "robust_v2": _history_metrics(rows)}


def run() -> dict:
    root = Path(__file__).resolve().parents[2]
    fixture = json.loads(
        (root / "tests/fixtures/buyback_forecast_september_2026.json").read_text()
    )
    activity = {row.day: row for row in load_full_activity()}
    for row in fixture["activity_overlay"]:
        day = date.fromisoformat(row["trading_date"])
        activity[day] = Activity(
            day, Decimal(str(row["last_price_nok"])), row["volume_shares"]
        )
    observations = sorted(activity.values(), key=lambda row: row.day)
    cumulative = 0
    weeks = []
    for row in fixture["weeks"]:
        cumulative += row["actual_shares"]
        weeks.append(
            Week(
                "2026-06-08",
                date.fromisoformat(row["period_start"]),
                date.fromisoformat(row["period_end"]),
                row["actual_shares"],
                cumulative,
                fixture["program_max_shares"],
            )
        )
    current = replay(observations, weeks)
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "validation.db")
        init_database(database)
        seed_curated_history(database)
        seed_known_official_buybacks(database)
        older_weeks = _actual_weeks(database)
    older = replay(observations, older_weeks)
    return {
        "sources": fixture["sources"],
        "evaluation": "Retrospective replay, not an untouched holdout or archived forecast. Both models use the same positive-volume observations and exchange calendar. Publication vintages and historical price-cap changes are not reconstructed.",
        "current_program": comparison(current),
        "current_program_before_september": comparison(
            [row for row in current if row["period_start"] < "2026-08-31"]
        ),
        "older_programs": comparison(older),
        "older_by_program": {
            program: comparison(
                replay(
                    observations,
                    [week for week in older_weeks if week.program_start == program],
                )
            )
            for program in sorted({week.program_start for week in older_weeks})
        },
        "recent_weeks": [
            {
                "from": row["period_start"],
                "actual": row["actual_shares"],
                "legacy": round(row["legacy_prediction_shares"]),
                "robust_v2": round(row["walk_forward_prediction_shares"]),
            }
            for row in current[-4:]
        ],
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
