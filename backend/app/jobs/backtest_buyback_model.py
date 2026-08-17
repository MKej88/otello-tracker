from __future__ import annotations

import argparse
import csv
import json
import statistics
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.buybacks.official_backfill import ZERO_PURCHASE_WEEKS, seed_known_official_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.jobs.backtest_buyback_forecast import Activity, load_activity
from app.newsweb import collect_newsweb_buybacks

PRE_EURONEXT_PATH = (
    Path(__file__).resolve().parents[1]
    / "buybacks"
    / "data"
    / "otec_investing_pre_euronext_2024.csv"
)

SAFE_HARBOUR_SHARE = 0.25
LOOKBACK = 20
FIRST_COMPARABLE_PROGRAM = "2024-07-22"
ZERO_PURCHASE_PROGRAM = "2025-09-22"
BASELINE_MODEL = "production_exact"
MIN_TRAIN_WEEKS = 6
RECENT_HOLDOUT_WEEKS = 6


@dataclass(frozen=True)
class Week:
    program_start: str
    period_start: date
    period_end: date
    actual_shares: int
    cumulative_shares: int
    max_program_shares: int


@dataclass(frozen=True)
class Model:
    name: str
    volume: str
    utilization: str
    cold_start: str = "one"


@dataclass(frozen=True)
class PredictionRecord:
    model: str
    program_start: str
    period_start: str
    period_end: str
    actual: float
    predicted: float
    capacity: float
    utilization: float


MODELS = [
    Model("production_exact", "adv20", "median8", "one"),
    Model("adv20_weighted6", "adv20", "weighted6", "one"),
    Model("trend_median8", "trend", "median8", "one"),
    Model("trend_weighted6", "trend", "weighted6", "one"),
    Model("production_with_history_cold_start", "adv20", "median8", "global_weighted6"),
]


def _weighted(values: list[float]) -> float:
    if not values:
        return 1.0
    weights = list(range(1, len(values) + 1))
    return sum(value * weight for value, weight in zip(values, weights)) / sum(weights)


def _median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 1.0


def load_full_activity() -> list[Activity]:
    """Extend the authoritative Euronext seed only where it has no older row.

    The supplement is a user-supplied Investing.com export that was validated against
    overlapping Euronext history. Euronext always wins on overlapping dates.
    """
    activity = {item.day: item for item in load_activity()}
    with PRE_EURONEXT_PATH.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            day = date.fromisoformat(row["date"])
            if day in activity:
                continue
            activity[day] = Activity(
                day=day,
                close=Decimal(row["close_nok"]),
                volume=int(row["volume_shares"]),
            )
    return sorted(activity.values(), key=lambda item: item.day)


def _actual_weeks(database_path: str) -> list[Week]:
    with get_connection(database_path) as connection:
        program_rows = connection.execute(
            """
            SELECT start_date, max_shares
            FROM buyback_programs
            WHERE start_date >= ?
            ORDER BY start_date
            """,
            (FIRST_COMPARABLE_PROGRAM,),
        ).fetchall()
        rows = connection.execute(
            """
            SELECT p.start_date AS program_start, p.max_shares,
                   b.period_start, b.trade_date AS period_end,
                   b.shares, b.cumulative_program_shares
            FROM buybacks b
            JOIN buyback_programs p ON p.id=b.program_id
            WHERE p.start_date >= ? AND b.period_start IS NOT NULL
            ORDER BY b.period_start, b.trade_date, b.id
            """,
            (FIRST_COMPARABLE_PROGRAM,),
        ).fetchall()

    max_by_program = {
        str(row["start_date"]): int(row["max_shares"])
        for row in program_rows
        if row["start_date"] is not None and row["max_shares"] is not None
    }
    result = [
        Week(
            program_start=str(row["program_start"]),
            period_start=date.fromisoformat(str(row["period_start"])),
            period_end=date.fromisoformat(str(row["period_end"])),
            actual_shares=int(row["shares"]),
            cumulative_shares=int(row["cumulative_program_shares"]),
            max_program_shares=int(row["max_shares"]),
        )
        for row in rows
    ]

    # The schema intentionally has no zero-share buyback rows. Preserve the documented
    # no-purchase weeks so models are penalized for forecasting activity when none occurred.
    zero_program_max = max_by_program.get(ZERO_PURCHASE_PROGRAM)
    if zero_program_max is not None:
        by_key = {(item.program_start, item.period_end): item for item in result}
        for start_text, end_text, cumulative, _amount in ZERO_PURCHASE_WEEKS:
            key = (ZERO_PURCHASE_PROGRAM, date.fromisoformat(end_text))
            if key in by_key:
                continue
            result.append(
                Week(
                    program_start=ZERO_PURCHASE_PROGRAM,
                    period_start=date.fromisoformat(start_text),
                    period_end=date.fromisoformat(end_text),
                    actual_shares=0,
                    cumulative_shares=int(cumulative),
                    max_program_shares=zero_program_max,
                )
            )
    return sorted(result, key=lambda item: (item.period_start, item.period_end))


def _capacity(activity: list[Activity], week: Week, remaining: int, volume_model: str) -> float | None:
    # Match production SQL semantics exactly: zero-volume rows do not count as an ADV
    # observation or a trading day for this forecast proxy.
    prior = [item for item in activity if item.day < week.period_start and item.volume > 0][-LOOKBACK:]
    period = [
        item
        for item in activity
        if week.period_start <= item.day <= week.period_end and item.volume > 0
    ]
    if len(prior) < LOOKBACK or not period:
        return None

    volumes = [float(item.volume) for item in prior]
    adv20 = statistics.mean(volumes)
    if volume_model == "adv20":
        projected = adv20
    elif volume_model == "trend":
        adv5 = statistics.mean(volumes[-5:])
        ratio = adv5 / adv20 if adv20 else 1.0
        ratio = max(0.60, min(1.60, ratio))
        projected = adv20 * (0.65 + 0.35 * ratio)
    else:
        raise ValueError(f"Unknown volume model: {volume_model}")

    return min(float(remaining), SAFE_HARBOUR_SHARE * projected * len(period))


def _factor(model: Model, same_program: list[float], global_utils: list[float]) -> float:
    if len(same_program) < 2:
        if model.cold_start == "global_weighted6" and global_utils:
            factor = _weighted(global_utils[-6:])
        else:
            factor = 1.0
    elif model.utilization == "median8":
        factor = _median(same_program[-8:])
    elif model.utilization == "weighted6":
        factor = _weighted(same_program[-6:])
    else:
        raise ValueError(f"Unknown utilization model: {model.utilization}")
    return max(0.0, min(1.10, factor))


def simulate(activity: list[Activity], weeks: list[Week]) -> dict[str, list[PredictionRecord]]:
    histories = {model.name: [] for model in MODELS}
    cumulative: dict[str, int] = {}
    same_utils: dict[str, dict[str, list[float]]] = {model.name: {} for model in MODELS}
    global_utils: dict[str, list[float]] = {model.name: [] for model in MODELS}

    for week in weeks:
        remaining = max(0, week.max_program_shares - cumulative.get(week.program_start, 0))
        for model in MODELS:
            capacity = _capacity(activity, week, remaining, model.volume)
            if capacity is None:
                continue
            same = same_utils[model.name].setdefault(week.program_start, [])
            factor = _factor(model, same, global_utils[model.name])
            predicted = min(float(remaining), capacity * factor)
            utilization = week.actual_shares / capacity if capacity > 0 else 0.0
            histories[model.name].append(
                PredictionRecord(
                    model=model.name,
                    program_start=week.program_start,
                    period_start=week.period_start.isoformat(),
                    period_end=week.period_end.isoformat(),
                    actual=float(week.actual_shares),
                    predicted=float(predicted),
                    capacity=float(capacity),
                    utilization=float(utilization),
                )
            )
            same.append(utilization)
            global_utils[model.name].append(utilization)
        cumulative[week.program_start] = week.cumulative_shares
    return histories


def metrics(records: list[PredictionRecord]) -> dict[str, Any]:
    if not records:
        return {"count": 0}
    abs_error = sum(abs(row.predicted - row.actual) for row in records)
    actual_total = sum(row.actual for row in records)
    predicted_total = sum(row.predicted for row in records)
    apes = [abs(row.predicted - row.actual) / row.actual for row in records if row.actual > 0]
    return {
        "count": len(records),
        "mae_shares": round(abs_error / len(records), 1),
        "wmape_pct": round(abs_error / actual_total * 100, 2) if actual_total else None,
        "median_ape_pct": round(statistics.median(apes) * 100, 2) if apes else None,
        "within_10_pct": round(sum(value <= 0.10 for value in apes) / len(apes) * 100, 1) if apes else None,
        "within_20_pct": round(sum(value <= 0.20 for value in apes) / len(apes) * 100, 1) if apes else None,
        "bias_pct": round((predicted_total - actual_total) / actual_total * 100, 2) if actual_total else None,
    }


def _segment(
    rows: list[PredictionRecord],
    *,
    start: str | None = None,
    before: str | None = None,
    program: str | None = None,
    programs: set[str] | None = None,
) -> list[PredictionRecord]:
    result = rows
    if start is not None:
        result = [row for row in result if row.period_start >= start]
    if before is not None:
        result = [row for row in result if row.period_start < before]
    if program is not None:
        result = [row for row in result if row.program_start == program]
    if programs is not None:
        result = [row for row in result if row.program_start in programs]
    return result


def _wmape_score(rows: list[PredictionRecord]) -> float:
    if len(rows) < MIN_TRAIN_WEEKS:
        return float("inf")
    actual = sum(row.actual for row in rows)
    if actual <= 0:
        return float("inf")
    return sum(abs(row.predicted - row.actual) for row in rows) / actual


def pick_model(
    histories: dict[str, list[PredictionRecord]],
    *,
    before: str | None = None,
    include_programs: set[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    ranked: list[tuple[float, str, int]] = []
    for model in MODELS:
        rows = _segment(
            histories[model.name],
            before=before,
            programs=include_programs,
        )
        ranked.append((_wmape_score(rows), model.name, len(rows)))
    ranked.sort(key=lambda item: (item[0], item[1]))
    finite = [item for item in ranked if item[0] != float("inf")]
    selected = finite[0][1] if finite else BASELINE_MODEL
    detail = [
        {
            "model": name,
            "train_weeks": count,
            "wmape_pct": round(score * 100, 2) if score != float("inf") else None,
        }
        for score, name, count in ranked
    ]
    return selected, detail


def build_validation_report(histories: dict[str, list[PredictionRecord]]) -> dict[str, Any]:
    baseline = histories.get(BASELINE_MODEL, [])
    if not baseline:
        return {"ready": False, "status": "NO_COMPARABLE_HISTORY"}

    programs = sorted({row.program_start for row in baseline})
    latest_program = programs[-1]
    latest_year = int(max(row.period_end for row in baseline)[:4])
    latest_year_start = f"{latest_year:04d}-01-01"

    pre_year_model, pre_year_training = pick_model(histories, before=latest_year_start)
    latest_year_holdout = {
        "year": latest_year,
        "selected_model": pre_year_model,
        "training": pre_year_training,
        "baseline": metrics(_segment(histories[BASELINE_MODEL], start=latest_year_start)),
        "selected": metrics(_segment(histories[pre_year_model], start=latest_year_start)),
    }

    pre_program_model, pre_program_training = pick_model(histories, before=latest_program)
    latest_program_holdout = {
        "program": latest_program,
        "selected_model": pre_program_model,
        "training": pre_program_training,
        "baseline": metrics(_segment(histories[BASELINE_MODEL], program=latest_program)),
        "selected": metrics(_segment(histories[pre_program_model], program=latest_program)),
    }

    latest_baseline_rows = _segment(histories[BASELINE_MODEL], program=latest_program)
    late_holdout: dict[str, Any] | None = None
    late_model: str | None = None
    if len(latest_baseline_rows) > 4:
        cutoff = latest_baseline_rows[4].period_start
        late_model, late_training = pick_model(histories, before=cutoff)
        late_holdout = {
            "cutoff": cutoff,
            "selected_model": late_model,
            "training": late_training,
            "baseline": metrics(
                _segment(histories[BASELINE_MODEL], start=cutoff, program=latest_program)
            ),
            "selected": metrics(
                _segment(histories[late_model], start=cutoff, program=latest_program)
            ),
        }

    program_start_holdouts: list[dict[str, Any]] = []
    previous: set[str] = set()
    for program in programs:
        if previous:
            selected, _ = pick_model(histories, include_programs=previous)
            program_start_holdouts.append(
                {
                    "program": program,
                    "selected_model": selected,
                    "baseline": metrics(_segment(histories[BASELINE_MODEL], program=program)),
                    "selected": metrics(_segment(histories[selected], program=program)),
                }
            )
        previous.add(program)

    recent_start = None
    if len(latest_baseline_rows) >= RECENT_HOLDOUT_WEEKS:
        recent_start = latest_baseline_rows[-RECENT_HOLDOUT_WEEKS].period_start

    replacement_signal = "KEEP_PRODUCTION"
    replacement_candidate = None
    if late_holdout is not None and late_model == pre_program_model and late_model != BASELINE_MODEL:
        current_base = latest_program_holdout["baseline"].get("wmape_pct")
        current_selected = latest_program_holdout["selected"].get("wmape_pct")
        late_base = late_holdout["baseline"].get("wmape_pct")
        late_selected = late_holdout["selected"].get("wmape_pct")
        if (
            current_base is not None
            and current_selected is not None
            and late_base is not None
            and late_selected is not None
            and current_selected < current_base
            and late_selected < late_base
        ):
            replacement_signal = "CHALLENGER_WORTH_REVIEW"
            replacement_candidate = late_model

    comparison = {
        model.name: {
            "all_history": metrics(histories[model.name]),
            "latest_year": metrics(_segment(histories[model.name], start=latest_year_start)),
            "latest_program": metrics(_segment(histories[model.name], program=latest_program)),
            "latest_program_recent": (
                metrics(_segment(histories[model.name], start=recent_start, program=latest_program))
                if recent_start is not None
                else {"count": 0}
            ),
        }
        for model in MODELS
    }

    return {
        "ready": True,
        "status": "OK",
        "coverage": {
            "first_week": baseline[0].period_start,
            "last_week": baseline[-1].period_end,
            "weeks": len(baseline),
            "programs": programs,
            "latest_program": latest_program,
        },
        "comparison": comparison,
        "latest_year_holdout": latest_year_holdout,
        "latest_program_holdout": latest_program_holdout,
        "late_latest_program_holdout": late_holdout,
        "program_start_holdouts": program_start_holdouts,
        "replacement": {
            "signal": replacement_signal,
            "candidate": replacement_candidate,
            "policy": (
                "Diagnostic only. Keep production unless the same challenger, selected without "
                "future data, beats production on both the whole latest-program holdout and the "
                "later recent-weeks holdout. Any production change still requires explicit review."
            ),
        },
    }


def run_model_validation(
    *,
    to_date: str | None = None,
    refresh_newsweb: bool = False,
) -> dict[str, Any]:
    to_date = to_date or date.today().isoformat()
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "buyback-model-validation.db")
        init_database(database)
        seed_curated_history(database)
        seed_known_official_buybacks(database)

        newsweb: dict[str, Any] = {"status": "SKIPPED"}
        if refresh_newsweb:
            live = collect_newsweb_buybacks(
                database,
                from_date="2025-09-22",
                to_date=to_date,
                timeout=30,
            )
            newsweb = {
                "status": live.get("status"),
                "discovered": live.get("discovered"),
                "ingested": live.get("ingested"),
                "errors": live.get("errors"),
            }

        activity = load_full_activity()
        weeks = _actual_weeks(database)
        histories = simulate(activity, weeks)
        validation = build_validation_report(histories)
        return {
            "source_validation": {
                "first_comparable_program": FIRST_COMPARABLE_PROGRAM,
                "official_euronext_history_from": "2024-08-19",
                "pre_euronext_source": (
                    "Investing.com user export; retained only before official Euronext coverage "
                    "and previously validated against 497 overlapping Euronext rows"
                ),
                "pre_euronext_overlap_mean_abs_volume_error_pct": 0.0076,
            },
            "newsweb": newsweb,
            **validation,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strict walk-forward and holdout validation of the Otello buyback forecast model."
    )
    parser.add_argument("--to", default=date.today().isoformat())
    parser.add_argument(
        "--refresh-newsweb",
        action="store_true",
        help="Refresh recent official buyback notices before running the validation.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run_model_validation(to_date=args.to, refresh_newsweb=args.refresh_newsweb),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
