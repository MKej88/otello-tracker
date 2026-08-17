from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.marketdata.oslo_calendar import oslo_bors_trading_days

SAFE_HARBOUR_SHARE = Decimal("0.25")
LOOKBACK_DAYS = 20
RECENT_PROGRAM_WEEKS = 8
METHOD_VERSION = "otec-buyback-safe-harbour-program-v1"


@dataclass(frozen=True)
class ProgramWeek:
    period_start: date
    period_end: date
    actual_shares: int
    cumulative_shares: int


def _median(values: list[float], default: float) -> float:
    return float(statistics.median(values)) if values else default


def _next_monday(after: date) -> date:
    delta = (7 - after.weekday()) % 7
    if delta == 0:
        delta = 7
    return after + timedelta(days=delta)


def _activity_before(connection, day: date, *, limit: int = LOOKBACK_DAYS):
    return connection.execute(
        """
        SELECT ma.trading_date, ma.volume_shares, ma.last_price_nok, ma.quality
        FROM market_activity ma JOIN instruments i ON i.id=ma.instrument_id
        WHERE i.symbol='OTEC' AND ma.trading_date < ? AND ma.volume_shares > 0
        ORDER BY ma.trading_date DESC LIMIT ?
        """,
        (day.isoformat(), limit),
    ).fetchall()[::-1]


def _activity_in_period(connection, start: date, end: date):
    return connection.execute(
        """
        SELECT ma.trading_date, ma.volume_shares
        FROM market_activity ma JOIN instruments i ON i.id=ma.instrument_id
        WHERE i.symbol='OTEC' AND ma.trading_date BETWEEN ? AND ? AND ma.volume_shares > 0
        ORDER BY ma.trading_date
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def _active_program(connection, as_of: date):
    return connection.execute(
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
    ).fetchone()


def _program_weeks(connection, program_id: int) -> list[ProgramWeek]:
    rows = connection.execute(
        """
        SELECT b.period_start, b.trade_date, b.shares, b.cumulative_program_shares
        FROM buybacks b
        WHERE b.program_id=? AND b.period_start IS NOT NULL
        ORDER BY b.trade_date, b.id
        """,
        (program_id,),
    ).fetchall()
    return [
        ProgramWeek(
            period_start=date.fromisoformat(row["period_start"]),
            period_end=date.fromisoformat(row["trade_date"]),
            actual_shares=int(row["shares"]),
            cumulative_shares=int(row["cumulative_program_shares"]),
        )
        for row in rows
    ]


def _program_history(connection, program_id: int, max_shares: int) -> list[dict[str, Any]]:
    weeks = _program_weeks(connection, program_id)
    previous_cumulative = 0
    observed_utils: list[float] = []
    rows: list[dict[str, Any]] = []
    for week in weeks:
        lookback = _activity_before(connection, week.period_start)
        period_activity = _activity_in_period(connection, week.period_start, week.period_end)
        if len(lookback) < LOOKBACK_DAYS or not period_activity:
            previous_cumulative = week.cumulative_shares
            continue
        adv20 = sum(int(item["volume_shares"]) for item in lookback) / LOOKBACK_DAYS
        capacity = float(SAFE_HARBOUR_SHARE) * adv20 * len(period_activity)
        remaining = max(0, max_shares - previous_cumulative)
        capacity_estimate = min(capacity, float(remaining))

        if len(observed_utils) >= 2:
            factor = _median(observed_utils[-RECENT_PROGRAM_WEEKS:], 1.0)
        else:
            factor = 1.0
        factor = max(0.0, min(1.10, factor))
        predicted = min(float(remaining), capacity_estimate * factor)
        utilization = week.actual_shares / capacity_estimate if capacity_estimate > 0 else 0.0
        rows.append(
            {
                "period_start": week.period_start.isoformat(),
                "period_end": week.period_end.isoformat(),
                "actual_shares": week.actual_shares,
                "adv20_shares": adv20,
                "trading_days": len(period_activity),
                "week_start_capacity_estimate_shares": capacity_estimate,
                "utilization": utilization,
                "walk_forward_factor": factor,
                "walk_forward_prediction_shares": predicted,
                "absolute_error_shares": abs(predicted - week.actual_shares),
            }
        )
        observed_utils.append(utilization)
        previous_cumulative = week.cumulative_shares
    return rows


def _history_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"weeks": 0}
    pct_errors = [
        row["absolute_error_shares"] / row["actual_shares"]
        for row in rows if row["actual_shares"] > 0
    ]
    absolute = sum(float(row["absolute_error_shares"]) for row in rows)
    actual = sum(float(row["actual_shares"]) for row in rows)
    return {
        "weeks": len(rows),
        "median_ape_pct": round(_median(pct_errors, 0.0) * 100, 2) if pct_errors else None,
        "wmape_pct": round(absolute / actual * 100, 2) if actual else None,
        "within_10_pct": round(sum(value <= 0.10 for value in pct_errors) / len(pct_errors) * 100, 1) if pct_errors else None,
        "within_20_pct": round(sum(value <= 0.20 for value in pct_errors) / len(pct_errors) * 100, 1) if pct_errors else None,
    }


def buyback_forecast(
    database_path: str | None = None,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Forecast the week after the latest published Otello buyback status.

    The 25% rule is applied to ADV20 frozen at the start of the forecast week. This is an
    ex-ante capacity estimate, not the exact legal weekly ceiling: Safe Harbour is tested
    separately on each purchase day using that day's rolling prior-20-day ADV.
    """
    as_of = date.fromisoformat(as_of_date) if as_of_date else date.today()
    with get_connection(database_path) as connection:
        program = _active_program(connection, as_of)
        if program is None:
            return {"ready": False, "status": "NO_ACTIVE_PROGRAM", "methodology_version": METHOD_VERSION}
        latest_end = date.fromisoformat(program["latest_period_end"])
        period_start = _next_monday(latest_end)
        period_end = period_start + timedelta(days=4)
        trading_days = oslo_bors_trading_days(period_start, period_end)

        if as_of > period_end:
            return {
                "ready": False,
                "status": "PROGRAM_STATUS_STALE",
                "methodology_version": METHOD_VERSION,
                "as_of_date": as_of.isoformat(),
                "latest_period_end": latest_end.isoformat(),
                "forecast_week": {
                    "from": period_start.isoformat(),
                    "to": period_end.isoformat(),
                    "expected_trading_days": len(trading_days),
                    "trading_dates": [item.isoformat() for item in trading_days],
                },
            }

        lookback = _activity_before(connection, period_start)
        if len(lookback) < LOOKBACK_DAYS:
            return {
                "ready": False,
                "status": "INSUFFICIENT_VOLUME_HISTORY",
                "required_days": LOOKBACK_DAYS,
                "available_days": len(lookback),
                "methodology_version": METHOD_VERSION,
            }
        adv20 = sum(int(item["volume_shares"]) for item in lookback) / LOOKBACK_DAYS
        expected_days = len(trading_days)
        remaining = max(0, int(program["max_shares"]) - int(program["cumulative_program_shares"] or 0))
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
                "methodology_version": METHOD_VERSION,
                "forecast_week": {
                    "from": period_start.isoformat(),
                    "to": period_end.isoformat(),
                    "expected_trading_days": 0,
                    "trading_dates": [],
                },
            }

        capacity = float(SAFE_HARBOUR_SHARE) * adv20 * expected_days
        capacity_estimate = min(capacity, float(remaining))
        history = _program_history(connection, int(program["id"]), int(program["max_shares"]))
        recent = history[-RECENT_PROGRAM_WEEKS:]
        recent_utils = [float(row["utilization"]) for row in recent]
        factor = max(0.0, min(1.10, _median(recent_utils, 1.0)))
        base_case = min(float(remaining), capacity_estimate * factor)

        error_ratios = [
            float(row["absolute_error_shares"]) / float(row["week_start_capacity_estimate_shares"])
            for row in recent if float(row["week_start_capacity_estimate_shares"]) > 0
        ]
        band = _median(error_ratios, 0.12)
        low = max(0.0, base_case - capacity_estimate * band)
        high_reference = min(float(remaining), capacity_estimate * 1.10)
        high = min(high_reference, base_case + capacity_estimate * band)

        last = lookback[-1]
        last_close = Decimal(last["last_price_nok"]) if last["last_price_nok"] is not None else None
        max_price = Decimal(program["max_price_nok"]) if program["max_price_nok"] is not None else None
        price_state = "UNKNOWN"
        price_headroom_pct: float | None = None
        warning: str | None = None
        if last_close is not None and max_price is not None and last_close > 0:
            price_headroom_pct = float((max_price / last_close - Decimal("1")) * Decimal("100"))
            if last_close > max_price:
                price_state = "ABOVE_CAP"
                warning = "Latest close is above the program price cap; next-week execution depends on the market trading back below the cap or a disclosed mandate change."
                low = 0.0
                high = max(high, base_case)
                base_case = 0.0
            elif price_headroom_pct <= 3.0:
                price_state = "TIGHT"
                warning = "Latest close is within 3% of the program price cap; execution may be price-constrained."
                low = max(0.0, base_case - capacity_estimate * max(band, 0.20))
            else:
                price_state = "OPEN"

        metrics = _history_metrics(history)
        if price_state == "ABOVE_CAP":
            confidence = "LOW"
        elif price_state in {"TIGHT", "UNKNOWN"}:
            confidence = "MEDIUM"
        elif len(history) >= 6 and (metrics.get("median_ape_pct") or 100) <= 10:
            confidence = "HIGH"
        else:
            confidence = "MEDIUM"

        return {
            "ready": True,
            "status": "OK" if price_state != "ABOVE_CAP" else "PRICE_CAP_BLOCKED",
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
                "safe_harbour_share": float(SAFE_HARBOUR_SHARE),
                "week_start_capacity_estimate_shares": round(capacity_estimate),
                "volume_through": last["trading_date"],
                "volume_source_quality": last["quality"],
                "note": "Week-start capacity is an ex-ante proxy; the regulatory 25% limit is recalculated for each purchase day from its preceding 20 trading days when the program does not state a fixed volume.",
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
            "recent_program_weeks": recent,
        }
