from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.buybacks.official_backfill import ZERO_PURCHASE_WEEKS, seed_known_official_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.newsweb import collect_newsweb_buybacks

ACTIVITY_PATH = Path(__file__).resolve().parents[1] / "buybacks" / "data" / "otec_euronext_daily_activity_2024_2026.csv"
SAFE_HARBOUR_VOLUME_SHARE = Decimal("0.25")
LOOKBACK_TRADING_DAYS = 20
PERIOD_RE = re.compile(r"during (\d{4}-\d{2}-\d{2})[–-](\d{4}-\d{2}-\d{2})")

# Documented program-price limits. The 22 Sep 2025 program started at NOK 15;
# Otello announced an increase to NOK 20 on 18 Nov 2025. For a weekly ex-ante
# forecast made before the week starts, that surprise update is intentionally not
# assumed for the 17-21 Nov week. It becomes known for the following week.
PROGRAM_PRICE_LIMITS: dict[str, tuple[tuple[str, Decimal], ...]] = {
    "2025-04-07": (("2025-04-07", Decimal("15")),),
    "2025-06-16": (("2025-06-16", Decimal("15")),),
    "2025-09-22": (
        ("2025-09-22", Decimal("15")),
        ("2025-11-24", Decimal("20")),
    ),
    "2026-02-09": (("2026-02-09", Decimal("20")),),
    "2026-06-08": (("2026-06-08", Decimal("20")),),
}


@dataclass(frozen=True)
class Activity:
    day: date
    close: Decimal
    volume: int


@dataclass(frozen=True)
class ActualWeek:
    program_start: str
    period_start: date
    period_end: date
    actual_shares: int
    cumulative_shares: int
    max_program_shares: int


@dataclass
class BacktestRow:
    program_start: str
    period_start: str
    period_end: str
    trading_days: int
    adv20: float
    last_close: float
    price_limit: float | None
    price_state: str
    capacity_shares: float
    remaining_before: int
    hard_capacity_shares: float
    actual_shares: int
    utilization: float
    capacity_prediction: float
    rolling_prediction: float
    price_aware_prediction: float


def load_activity(path: Path = ACTIVITY_PATH) -> list[Activity]:
    rows: list[Activity] = []
    with path.open(encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            rows.append(
                Activity(
                    day=date.fromisoformat(raw["date"]),
                    close=Decimal(raw["close_nok"]),
                    volume=int(raw["volume_shares"]),
                )
            )
    rows.sort(key=lambda item: item.day)
    if not rows:
        raise ValueError("OTEC activity seed is empty")
    return rows


def _price_limit(program_start: str, period_start: date) -> Decimal | None:
    regimes = PROGRAM_PRICE_LIMITS.get(program_start)
    if not regimes:
        return None
    applicable = [limit for effective, limit in regimes if date.fromisoformat(effective) <= period_start]
    return applicable[-1] if applicable else None


def _price_state(last_close: Decimal, limit: Decimal | None) -> str:
    if limit is None:
        return "UNKNOWN"
    if last_close > limit:
        return "ABOVE_CAP"
    headroom = limit / last_close - Decimal("1") if last_close else Decimal("0")
    if headroom <= Decimal("0.03"):
        return "TIGHT"
    return "OPEN"


def _period_from_description(description: str | None) -> tuple[date, date] | None:
    if not description:
        return None
    match = PERIOD_RE.search(description)
    if not match:
        return None
    return date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2))


def _actual_weeks(database_path: str) -> list[ActualWeek]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT p.start_date AS program_start, p.max_shares,
                   b.trade_date, b.shares, b.cumulative_program_shares,
                   cm.description
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            LEFT JOIN cash_movements cm
              ON cm.movement_type = 'OTELLO_BUYBACK'
             AND cm.movement_date = b.trade_date
            WHERE b.trade_date >= '2025-04-07'
            ORDER BY b.trade_date, b.id
            """
        ).fetchall()

    result: list[ActualWeek] = []
    for row in rows:
        period = _period_from_description(row["description"])
        if period is None:
            continue
        start, end = period
        program_start = str(row["program_start"])
        if program_start not in PROGRAM_PRICE_LIMITS:
            continue
        result.append(
            ActualWeek(
                program_start=program_start,
                period_start=start,
                period_end=end,
                actual_shares=int(row["shares"]),
                cumulative_shares=int(row["cumulative_program_shares"]),
                max_program_shares=int(row["max_shares"]),
            )
        )

    # Zero-purchase weeks are deliberately not persisted in `buybacks` because the
    # table requires shares > 0. Add the two documented Sep-2025-program zero weeks
    # so the forecast is penalized for failing to detect the NOK 15 price-cap blockage.
    by_key = {(item.program_start, item.period_end): item for item in result}
    for start_text, end_text, cumulative, _amount in ZERO_PURCHASE_WEEKS:
        key = ("2025-09-22", date.fromisoformat(end_text))
        if key in by_key:
            continue
        item = ActualWeek(
            program_start="2025-09-22",
            period_start=date.fromisoformat(start_text),
            period_end=date.fromisoformat(end_text),
            actual_shares=0,
            cumulative_shares=int(cumulative),
            max_program_shares=3_689_541,
        )
        result.append(item)
        by_key[key] = item

    return sorted(result, key=lambda item: (item.period_start, item.period_end))


def _median(values: list[float], default: float = 1.0) -> float:
    return float(statistics.median(values)) if values else default


def _recent(values: list[float], n: int = 8) -> list[float]:
    return values[-n:]


def build_backtest(activity: list[Activity], actuals: list[ActualWeek]) -> list[BacktestRow]:
    open_days = [item for item in activity if item.volume > 0]
    history_by_program: dict[str, list[BacktestRow]] = {}
    all_history: list[BacktestRow] = []
    previous_cumulative: dict[str, int] = {}
    output: list[BacktestRow] = []

    for week in actuals:
        prior = [item for item in open_days if item.day < week.period_start]
        if len(prior) < LOOKBACK_TRADING_DAYS:
            continue
        lookback = prior[-LOOKBACK_TRADING_DAYS:]
        adv20 = sum(item.volume for item in lookback) / LOOKBACK_TRADING_DAYS
        last_close = lookback[-1].close
        period_days = [
            item for item in open_days
            if week.period_start <= item.day <= week.period_end
        ]
        if not period_days:
            continue
        trading_days = len(period_days)
        capacity = float(SAFE_HARBOUR_VOLUME_SHARE) * adv20 * trading_days
        prev_cumulative = previous_cumulative.get(week.program_start, 0)
        remaining = max(0, week.max_program_shares - prev_cumulative)
        hard_capacity = min(capacity, float(remaining))
        limit = _price_limit(week.program_start, week.period_start)
        state = _price_state(last_close, limit)

        # Model 1: pure Safe Harbour capacity, capped only by remaining program shares.
        capacity_prediction = hard_capacity

        # Model 2: walk-forward rolling utilization. It may use only already completed
        # weeks, so no future week leaks into its own prediction.
        prior_rows = all_history
        prior_utils = [row.utilization for row in prior_rows if row.hard_capacity_shares > 0]
        rolling_factor = _median(_recent(prior_utils, 8), default=1.0)
        rolling_factor = max(0.0, min(1.10, rolling_factor))
        rolling_prediction = hard_capacity * rolling_factor

        # Model 3: price-aware walk-forward utilization. Use prior weeks in the same
        # price-cap state where possible; otherwise fall back to recent global behavior.
        comparable = [
            row.utilization for row in prior_rows
            if row.price_state == state and row.hard_capacity_shares > 0
        ]
        if len(comparable) >= 3:
            price_factor = _median(_recent(comparable, 8), default=rolling_factor)
        else:
            price_factor = rolling_factor
        price_factor = max(0.0, min(1.10, price_factor))
        price_prediction = hard_capacity * price_factor

        utilization = week.actual_shares / hard_capacity if hard_capacity > 0 else 0.0
        row = BacktestRow(
            program_start=week.program_start,
            period_start=week.period_start.isoformat(),
            period_end=week.period_end.isoformat(),
            trading_days=trading_days,
            adv20=adv20,
            last_close=float(last_close),
            price_limit=float(limit) if limit is not None else None,
            price_state=state,
            capacity_shares=capacity,
            remaining_before=remaining,
            hard_capacity_shares=hard_capacity,
            actual_shares=week.actual_shares,
            utilization=utilization,
            capacity_prediction=capacity_prediction,
            rolling_prediction=rolling_prediction,
            price_aware_prediction=price_prediction,
        )
        output.append(row)
        all_history.append(row)
        history_by_program.setdefault(week.program_start, []).append(row)
        previous_cumulative[week.program_start] = week.cumulative_shares

    return output


def _metrics(rows: list[BacktestRow], attr: str) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    errors: list[float] = []
    pct_errors: list[float] = []
    actual_total = 0.0
    abs_error_total = 0.0
    within_10 = 0
    within_20 = 0
    nonzero = 0
    zero_predictions: list[float] = []
    predicted_total = 0.0

    for row in rows:
        predicted = float(getattr(row, attr))
        actual = float(row.actual_shares)
        error = predicted - actual
        errors.append(error)
        abs_error_total += abs(error)
        actual_total += actual
        predicted_total += predicted
        if actual > 0:
            nonzero += 1
            ape = abs(error) / actual
            pct_errors.append(ape)
            within_10 += ape <= 0.10
            within_20 += ape <= 0.20
        else:
            zero_predictions.append(predicted)

    return {
        "count": len(rows),
        "nonzero_count": nonzero,
        "zero_count": len(zero_predictions),
        "mae_shares": round(abs_error_total / len(rows), 1),
        "wmape_pct": round(abs_error_total / actual_total * 100, 2) if actual_total else None,
        "median_ape_pct": round(statistics.median(pct_errors) * 100, 2) if pct_errors else None,
        "within_10_pct": round(within_10 / nonzero * 100, 1) if nonzero else None,
        "within_20_pct": round(within_20 / nonzero * 100, 1) if nonzero else None,
        "bias_pct": round((predicted_total - actual_total) / actual_total * 100, 2) if actual_total else None,
        "mean_prediction_when_actual_zero": round(statistics.mean(zero_predictions), 1) if zero_predictions else None,
    }


def _forecast_next_week(
    activity: list[Activity],
    rows: list[BacktestRow],
    *,
    period_start: date,
    period_end: date,
    max_program_shares: int,
    cumulative_program_shares: int,
    price_limit: Decimal,
) -> dict[str, Any]:
    open_days = [item for item in activity if item.volume > 0 and item.day < period_start]
    lookback = open_days[-LOOKBACK_TRADING_DAYS:]
    if len(lookback) < LOOKBACK_TRADING_DAYS:
        raise ValueError("Insufficient 20-day OTEC volume history")
    adv20 = sum(item.volume for item in lookback) / LOOKBACK_TRADING_DAYS
    last_close = lookback[-1].close
    expected_days = sum(1 for offset in range((period_end - period_start).days + 1) if (period_start + timedelta(days=offset)).weekday() < 5)
    capacity = float(SAFE_HARBOUR_VOLUME_SHARE) * adv20 * expected_days
    remaining = max_program_shares - cumulative_program_shares
    hard_capacity = min(capacity, float(remaining))
    state = _price_state(last_close, price_limit)
    prior_utils = [row.utilization for row in rows if row.hard_capacity_shares > 0]
    rolling_factor = max(0.0, min(1.10, _median(_recent(prior_utils, 8), 1.0)))
    comparable = [row.utilization for row in rows if row.price_state == state and row.hard_capacity_shares > 0]
    price_factor = (
        _median(_recent(comparable, 8), rolling_factor)
        if len(comparable) >= 3
        else rolling_factor
    )
    price_factor = max(0.0, min(1.10, price_factor))
    base = hard_capacity * price_factor

    # A deliberately broad empirical interval around base. It is a forecast band,
    # not a legal limit; the legal/mandate ceiling is reported separately.
    recent_abs_ratio_errors = [
        abs(row.price_aware_prediction - row.actual_shares) / row.hard_capacity_shares
        for row in rows[-12:] if row.hard_capacity_shares > 0
    ]
    band = _median(recent_abs_ratio_errors, 0.15)
    low = max(0.0, base - hard_capacity * band)
    high = min(hard_capacity, base + hard_capacity * band)
    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "expected_trading_days": expected_days,
        "adv20_shares": round(adv20, 1),
        "safe_harbour_capacity_shares": round(capacity),
        "remaining_program_shares": remaining,
        "hard_capacity_shares": round(hard_capacity),
        "last_close_nok": float(last_close),
        "program_price_limit_nok": float(price_limit),
        "price_state": state,
        "model_utilization_factor": round(price_factor, 4),
        "base_case_shares": round(base),
        "range_low_shares": round(low),
        "range_high_shares": round(high),
        "range_method": "median absolute capacity-relative error over up to 12 latest backtest weeks",
    }


def run_live_backtest(*, to_date: str = "2026-08-14") -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        database_path = str(Path(directory) / "backtest.db")
        init_database(database_path)
        seed_curated_history(database_path)
        seed_known_official_buybacks(database_path)
        live = collect_newsweb_buybacks(
            database_path,
            from_date="2025-04-07",
            to_date=to_date,
            timeout=30,
        )
        activity = load_activity()
        actuals = _actual_weeks(database_path)
        rows = build_backtest(activity, actuals)

        with get_connection(database_path) as connection:
            latest = connection.execute(
                """
                SELECT b.cumulative_program_shares, p.max_shares, p.start_date
                FROM buybacks b JOIN buyback_programs p ON p.id=b.program_id
                WHERE p.start_date='2026-06-08'
                ORDER BY b.trade_date DESC, b.id DESC LIMIT 1
                """
            ).fetchone()
        current_forecast = None
        if latest is not None and to_date == "2026-08-14":
            current_forecast = _forecast_next_week(
                activity,
                rows,
                period_start=date(2026, 8, 17),
                period_end=date(2026, 8, 21),
                max_program_shares=int(latest["max_shares"]),
                cumulative_program_shares=int(latest["cumulative_program_shares"]),
                price_limit=Decimal("20"),
            )

        return {
            "source": {
                "volume": "Euronext historical OTEC export, Number of Shares",
                "actual_buybacks": "Oslo Bors NewsWeb / curated official Euronext gaps",
                "safe_harbour_volume_rule": "25% of average daily volume; model uses prior 20 trading days",
            },
            "newsweb": {
                "status": live.get("status"),
                "discovered": live.get("discovered"),
                "ingested": live.get("ingested"),
                "errors": live.get("errors"),
            },
            "period": {
                "from": rows[0].period_start if rows else None,
                "to": rows[-1].period_end if rows else None,
                "weeks": len(rows),
            },
            "metrics": {
                "capacity": _metrics(rows, "capacity_prediction"),
                "rolling_utilization": _metrics(rows, "rolling_prediction"),
                "price_aware_walk_forward": _metrics(rows, "price_aware_prediction"),
            },
            "current_forecast": current_forecast,
            "rows": [row.__dict__ for row in rows],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Live backtest of OTEC weekly buyback forecast")
    parser.add_argument("--to", default="2026-08-14")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = run_live_backtest(to_date=args.to)
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2, default=str))


if __name__ == "__main__":
    main()
