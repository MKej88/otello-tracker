from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from src.oslo_calendar import oslo_bors_trading_days

from src.buyback_model import METHOD_VERSION, known_history, model_confidence, point_estimate, uncertainty_band

SAFE_HARBOUR_SHARE = Decimal("0.25")
LOOKBACK_DAYS = 20
RECENT_PROGRAM_WEEKS = 8
MAX_ACTIVITY_ROWS = 5000


@dataclass(frozen=True)
class ProgramWeek:
    period_start: date
    period_end: date
    actual_shares: int
    cumulative_shares: int
    published_date: date | None = None


def _median(values: list[float], default: float) -> float:
    return float(statistics.median(values)) if values else default


def _next_monday(after: date) -> date:
    delta = (7 - after.weekday()) % 7
    if delta == 0:
        delta = 7
    return after + timedelta(days=delta)


def _last_sunday(year: int, month: int) -> date:
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    last = first_next - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def _oslo_today() -> date:
    """Return Europe/Oslo date without relying on a system tzdata package."""
    now = datetime.now(timezone.utc)
    start = datetime.combine(
        _last_sunday(now.year, 3),
        datetime.min.time(),
        tzinfo=timezone.utc,
    ) + timedelta(hours=1)
    end = datetime.combine(
        _last_sunday(now.year, 10),
        datetime.min.time(),
        tzinfo=timezone.utc,
    ) + timedelta(hours=1)
    offset = timedelta(hours=2 if start <= now < end else 1)
    return (now + offset).date()


async def _activity_history(repository, before: date) -> list[dict[str, Any]]:
    """Load the newest bounded OTEC activity set once per forecast invocation.

    The previous Worker port issued two D1 queries for every historical program week.
    Fetching the ordered activity once preserves the exact model calculations while
    keeping D1 query count effectively constant as the active program gets older. The
    SQL reads newest-first so the safety bound can never discard current lookback rows;
    the returned list is reversed back to chronological order for the model.
    """
    rows = await repository.all(
        """
        SELECT ma.trading_date, ma.volume_shares, ma.last_price_nok, ma.quality
        FROM market_activity ma JOIN instruments i ON i.id=ma.instrument_id
        WHERE i.symbol='OTEC' AND ma.trading_date < ? AND ma.volume_shares > 0
        ORDER BY ma.trading_date DESC, ma.id DESC
        LIMIT ?
        """,
        (before.isoformat(), MAX_ACTIVITY_ROWS),
    )
    return rows[::-1]


def _activity_before(
    activity: list[dict[str, Any]],
    day: date,
    *,
    limit: int = LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    cutoff = day.isoformat()
    return [item for item in activity if str(item["trading_date"]) < cutoff][-limit:]


def _activity_in_period(
    activity: list[dict[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    start_text = start.isoformat()
    end_text = end.isoformat()
    return [
        item
        for item in activity
        if start_text <= str(item["trading_date"]) <= end_text
    ]


async def _active_program(repository, as_of: date):
    return await repository.first(
        """
        SELECT p.id, p.external_program_id, p.start_date, p.end_date, p.status,
               p.max_shares, p.max_price_nok,
               b.trade_date AS latest_period_end, b.cumulative_program_shares,
               b.treasury_shares_after
        FROM buybacks b JOIN buyback_programs p ON p.id=b.program_id
        WHERE p.status='ACTIVE'
          AND (p.start_date IS NULL OR p.start_date <= ?)
          AND (p.end_date IS NULL OR p.end_date >= ?)
        ORDER BY b.trade_date DESC, b.id DESC LIMIT 1
        """,
        (as_of.isoformat(), as_of.isoformat()),
    )


async def _program_weeks(repository, program_id: int) -> list[ProgramWeek]:
    rows = await repository.all(
        """
        SELECT b.period_start, b.trade_date, b.shares, b.cumulative_program_shares,
               sd.published_at
        FROM buybacks b
        LEFT JOIN source_documents sd ON sd.id=b.source_document_id
        WHERE b.program_id=? AND b.period_start IS NOT NULL
        ORDER BY b.trade_date, b.id
        """,
        (program_id,),
    )
    return [
        ProgramWeek(
            period_start=date.fromisoformat(row["period_start"]),
            period_end=date.fromisoformat(row["trade_date"]),
            actual_shares=int(row["shares"]),
            cumulative_shares=int(row["cumulative_program_shares"]),
            published_date=(date.fromisoformat(str(dict(row)["published_at"])[:10])
                            if dict(row).get("published_at") else None),
        )
        for row in rows
    ]


def _program_history(
    weeks: list[ProgramWeek],
    max_shares: int,
    activity: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, week in enumerate(weeks):
        lookback = _activity_before(activity, week.period_start)
        # Calendar days are knowable before the week; future feed coverage is not.
        days = len(oslo_bors_trading_days(week.period_start, week.period_end))
        if len(lookback) < LOOKBACK_DAYS or not days:
            continue
        prior_weeks = [
            item for item in weeks[:index]
            if item.period_end < week.period_start
            and (item.published_date is None or item.published_date < week.period_start)
        ]
        previous_cumulative = prior_weeks[-1].cumulative_shares if prior_weeks else 0
        remaining = max(0, max_shares - previous_cumulative)
        known = known_history(rows, week.period_start.isoformat())
        point = point_estimate(lookback, days, remaining, known)
        capacity = point["week_start_capacity_estimate_shares"]
        model_capacity = point["forecast_capacity_estimate_shares"]
        predicted = point["walk_forward_prediction_shares"]
        rows.append({
            **point,
            "period_start": week.period_start.isoformat(),
            "period_end": week.period_end.isoformat(),
            "published_date": week.published_date.isoformat() if week.published_date else None,
            "actual_shares": week.actual_shares,
            "trading_days": days,
            "utilization": week.actual_shares / capacity if capacity > 0 else 0.0,
            "forecast_utilization": week.actual_shares / model_capacity if model_capacity > 0 else 0.0,
            "absolute_error_shares": abs(predicted - week.actual_shares),
        })
    return rows


def _history_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"weeks": 0}
    pct_errors = [
        row["absolute_error_shares"] / row["actual_shares"]
        for row in rows
        if row["actual_shares"] > 0
    ]
    absolute = sum(float(row["absolute_error_shares"]) for row in rows)
    actual = sum(float(row["actual_shares"]) for row in rows)
    return {
        "weeks": len(rows),
        "median_ape_pct": round(_median(pct_errors, 0.0) * 100, 2) if pct_errors else None,
        "wmape_pct": round(absolute / actual * 100, 2) if actual else None,
        "within_10_pct": (
            round(sum(value <= 0.10 for value in pct_errors) / len(pct_errors) * 100, 1)
            if pct_errors
            else None
        ),
        "within_20_pct": (
            round(sum(value <= 0.20 for value in pct_errors) / len(pct_errors) * 100, 1)
            if pct_errors
            else None
        ),
    }


async def buyback_forecast(
    repository,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """D1 port of the validated Safe Harbour/program walk-forward estimator."""
    as_of = date.fromisoformat(as_of_date) if as_of_date else _oslo_today()
    program = await _active_program(repository, as_of)
    if program is None:
        return {
            "ready": False,
            "status": "NO_ACTIVE_PROGRAM",
            "as_of_date": as_of.isoformat(),
            "methodology_version": METHOD_VERSION,
        }

    latest_end = date.fromisoformat(program["latest_period_end"])
    period_start = _next_monday(latest_end)
    period_end = period_start + timedelta(days=4)
    trading_days = oslo_bors_trading_days(period_start, period_end)
    awaiting_program_update = as_of > period_end

    activity = await _activity_history(repository, period_start)
    lookback = _activity_before(activity, period_start)
    if len(lookback) < LOOKBACK_DAYS:
        return {
            "ready": False,
            "status": "INSUFFICIENT_VOLUME_HISTORY",
            "as_of_date": as_of.isoformat(),
            "required_days": LOOKBACK_DAYS,
            "available_days": len(lookback),
            "methodology_version": METHOD_VERSION,
        }

    adv20 = sum(int(item["volume_shares"]) for item in lookback) / LOOKBACK_DAYS
    expected_days = len(trading_days)
    remaining = max(
        0,
        int(program["max_shares"]) - int(program["cumulative_program_shares"] or 0),
    )
    if remaining == 0:
        return {
            "ready": False,
            "status": "PROGRAM_EXHAUSTED",
            "methodology_version": METHOD_VERSION,
            "as_of_date": as_of.isoformat(),
            "program": {
                "external_id": program["external_program_id"],
                "start_date": program["start_date"],
                "end_date": program["end_date"],
                "max_shares": int(program["max_shares"]),
                "cumulative_shares": int(program["cumulative_program_shares"] or 0),
                "remaining_shares": 0,
            },
        }
    if expected_days == 0:
        return {
            "ready": False,
            "status": "NO_TRADING_DAYS",
            "as_of_date": as_of.isoformat(),
            "methodology_version": METHOD_VERSION,
            "forecast_week": {
                "from": period_start.isoformat(),
                "to": period_end.isoformat(),
                "expected_trading_days": 0,
                "trading_dates": [],
            },
        }

    weeks = await _program_weeks(repository, int(program["id"]))
    history = _program_history(weeks, int(program["max_shares"]), activity)
    history = known_history(history, period_start.isoformat())
    recent = history[-RECENT_PROGRAM_WEEKS:]
    point = point_estimate(lookback, expected_days, remaining, history)
    capacity_estimate = point["week_start_capacity_estimate_shares"]
    forecast_capacity = point["forecast_capacity_estimate_shares"]
    factor = point["walk_forward_factor"]
    base_case = point["walk_forward_prediction_shares"]
    band = uncertainty_band(history)
    low = max(0.0, base_case - forecast_capacity * band)
    high_reference = min(float(remaining), capacity_estimate * 1.10)
    high = min(high_reference, base_case + forecast_capacity * band)

    last = lookback[-1]
    last_close = Decimal(str(last["last_price_nok"])) if last["last_price_nok"] is not None else None
    max_price = Decimal(str(program["max_price_nok"])) if program["max_price_nok"] is not None else None
    price_state = "UNKNOWN"
    price_headroom_pct: float | None = None
    warning: str | None = None
    if last_close is not None and max_price is not None and last_close > 0:
        price_headroom_pct = float((max_price / last_close - Decimal("1")) * Decimal("100"))
        if last_close > max_price:
            price_state = "ABOVE_CAP"
            warning = (
                "Latest close is above the program price cap; next-week execution depends on "
                "the market trading back below the cap or a disclosed mandate change."
            )
            low = 0.0
            high = max(high, base_case)
            base_case = 0.0
        elif price_headroom_pct <= 3.0:
            price_state = "TIGHT"
            warning = (
                "Latest close is within 3% of the program price cap; execution may be "
                "price-constrained."
            )
            low = max(0.0, base_case - capacity_estimate * max(band, 0.20))
        else:
            price_state = "OPEN"

    metrics = _history_metrics(history)
    confidence = model_confidence(history, price_state, point["volume_adjustment_pct"])

    return {
        "ready": True,
        "status": "OK" if price_state != "ABOVE_CAP" else "PRICE_CAP_BLOCKED",
        "awaiting_program_update": awaiting_program_update,
        "methodology_version": METHOD_VERSION,
        "as_of_date": as_of.isoformat(),
        "program": {
            "external_id": program["external_program_id"],
            "start_date": program["start_date"],
            "end_date": program["end_date"],
            "max_shares": int(program["max_shares"]),
            "cumulative_shares": int(program["cumulative_program_shares"] or 0),
            "remaining_shares": remaining,
            "max_price_nok": float(max_price) if max_price is not None else None,
        },
        "forecast_week": {
            "from": period_start.isoformat(),
            "to": period_end.isoformat(),
            "expected_trading_days": expected_days,
            "trading_dates": [item.isoformat() for item in trading_days],
        },
        "volume_model": {
            "adv20_shares": round(adv20, 1),
            "forecast_adv20_shares": round(point["forecast_adv20_shares"], 1),
            "forecast_capacity_estimate_shares": round(forecast_capacity),
            "volume_outlier_days": point["volume_outlier_days"],
            "volume_adjustment_pct": round(point["volume_adjustment_pct"], 1),
            "safe_harbour_share": float(SAFE_HARBOUR_SHARE),
            "week_start_capacity_estimate_shares": round(capacity_estimate),
            "volume_through": last["trading_date"],
            "volume_source_quality": last["quality"],
            "note": (
                "Week-start capacity is an ex-ante proxy; the regulatory 25% limit is "
                "recalculated for each purchase day from its preceding 20 trading days when "
                "the program does not state a fixed volume."
            ),
        },
        "price_model": {
            "latest_close_nok": float(last_close) if last_close is not None else None,
            "program_cap_nok": float(max_price) if max_price is not None else None,
            "headroom_pct": round(price_headroom_pct, 2) if price_headroom_pct is not None else None,
            "state": price_state,
        },
        "estimate": {
            "base_case_shares": round(base_case),
            "low_shares": round(low),
            "high_shares": round(high),
            "utilization_factor": round(factor, 4),
            "confidence": confidence,
            "warning": warning,
        },
        "active_program_backtest": metrics,
        "legacy_program_backtest": _history_metrics([
            {**row, "absolute_error_shares": abs(row["legacy_prediction_shares"] - row["actual_shares"])}
            for row in history
        ]),
        "backtest_kind": "RECALCULATED",
        "recent_program_weeks": recent,
    }
