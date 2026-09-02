from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from buyback_service import LOOKBACK_DAYS, SAFE_HARBOUR_SHARE, buyback_forecast
from estimated_nav_history import _share_count_driver

FULL_CALCULATION_VERSION = "full-market-nav-daily-v2"


def _completion(
    forecast: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    remaining_shares: int,
    program_end_date: str | None,
    latest_period_end: str | None,
) -> dict[str, Any]:
    estimate = forecast.get("estimate") or {}
    base = int(estimate.get("base_case_shares") or 0)
    actuals = [
        int(item.get("actual_shares") or 0)
        for item in history
        if int(item.get("actual_shares") or 0) > 0
    ]

    if base > 0:
        pace = base
        basis = "FORECAST_BASE"
    elif actuals:
        pace = int(round(statistics.median(actuals[-4:])))
        basis = "RECENT_ACTUAL_MEDIAN"
    else:
        pace = 0
        basis = "UNAVAILABLE"

    weeks = (
        math.ceil(remaining_shares / pace) if remaining_shares > 0 and pace > 0 else 0
    )
    forecast_week = forecast.get("forecast_week") or {}
    first_end = forecast_week.get("to")
    if not first_end and latest_period_end:
        first_end = (
            date.fromisoformat(latest_period_end) + timedelta(days=7)
        ).isoformat()

    completion_date = None
    if weeks > 0 and first_end:
        completion_date = (
            date.fromisoformat(str(first_end)) + timedelta(days=7 * (weeks - 1))
        ).isoformat()

    extends = bool(
        completion_date and program_end_date and completion_date > str(program_end_date)
    )
    return {
        "pace_shares_per_week": pace or None,
        "basis": basis,
        "estimated_weeks_remaining": weeks or None,
        "estimated_completion_date": completion_date,
        "program_end_date": program_end_date,
        "extends_beyond_program_end": extends,
        "price_cap_blocked": forecast.get("status") == "PRICE_CAP_BLOCKED",
    }


def _enrich_history(
    history: list[dict[str, Any]], volumes: dict[str, int]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in history:
        start = date.fromisoformat(str(item["period_start"]))
        end = date.fromisoformat(str(item["period_end"]))
        current = start
        market_volume = 0
        while current <= end:
            market_volume += volumes.get(current.isoformat(), 0)
            current += timedelta(days=1)
        actual = int(item.get("actual_shares") or 0)
        predicted = float(item.get("walk_forward_prediction_shares") or 0)
        capacity = float(item.get("week_start_capacity_estimate_shares") or 0)
        result.append(
            {
                **item,
                "market_volume_shares": market_volume or None,
                "actual_volume_share_pct": (
                    round(actual / market_volume * 100, 2) if market_volume else None
                ),
                "safe_harbour_utilization_pct": (
                    round(actual / capacity * 100, 1) if capacity else None
                ),
                "forecast_error_shares": round(predicted - actual),
                "forecast_error_pct": (
                    round((predicted / actual - 1) * 100, 1) if actual else None
                ),
            }
        )
    return result


async def _latest_week_metrics(repository, latest) -> dict[str, int | float | None]:
    empty = {
        "market_volume_shares": None,
        "volume_share_pct": None,
        "safe_harbour_capacity_shares": None,
        "safe_harbour_utilization_pct": None,
    }
    if latest is None or not latest.get("period_start") or not latest.get("trade_date"):
        return empty

    start = str(latest["period_start"])
    end = str(latest["trade_date"])
    period_activity = await repository.all(
        """
        SELECT ma.trading_date, ma.volume_shares
        FROM market_activity ma
        JOIN instruments i ON i.id=ma.instrument_id
        WHERE i.symbol='OTEC' AND ma.trading_date BETWEEN ? AND ? AND ma.volume_shares > 0
        ORDER BY ma.trading_date
        """,
        (start, end),
    )
    market_volume = sum(int(row["volume_shares"]) for row in period_activity)
    actual = int(latest.get("shares") or 0)
    result = {
        **empty,
        "market_volume_shares": market_volume or None,
        "volume_share_pct": (
            round(actual / market_volume * 100, 2) if market_volume else None
        ),
    }

    lookback = await repository.all(
        """
        SELECT ma.volume_shares
        FROM market_activity ma
        JOIN instruments i ON i.id=ma.instrument_id
        WHERE i.symbol='OTEC' AND ma.trading_date < ? AND ma.volume_shares > 0
        ORDER BY ma.trading_date DESC, ma.id DESC
        LIMIT ?
        """,
        (start, LOOKBACK_DAYS),
    )
    if len(lookback) < LOOKBACK_DAYS or not period_activity:
        return result

    adv20 = sum(int(row["volume_shares"]) for row in lookback) / LOOKBACK_DAYS
    max_shares = int(latest.get("max_shares") or 0)
    cumulative = int(latest.get("cumulative_program_shares") or 0)
    previous_cumulative = max(0, cumulative - actual)
    raw_capacity = float(SAFE_HARBOUR_SHARE) * adv20 * len(period_activity)
    capacity = (
        min(raw_capacity, float(max(0, max_shares - previous_cumulative)))
        if max_shares
        else raw_capacity
    )
    if capacity <= 0:
        return result
    result["safe_harbour_capacity_shares"] = round(capacity)
    result["safe_harbour_utilization_pct"] = round(actual / capacity * 100, 1)
    return result


def _normalize_latest_numeric_fields(payload: dict[str, Any] | None) -> None:
    """Keep SQLite/D1 JSON stable despite sub-cent binary-float representation noise."""
    if payload is None:
        return
    average_price = payload.get("avg_price_nok")
    if average_price is not None:
        payload["avg_price_nok"] = round(float(average_price), 13)


def _nav_effect(nav_snapshot, latest, shares) -> dict[str, float | None]:
    if nav_snapshot is None or latest is None or shares is None:
        return {"per_share_nok": None, "pct": None}
    bought = Decimal(str(latest.get("cumulative_program_shares") or 0))
    spent = Decimal(str(latest.get("cumulative_program_amount_nok") or 0))
    outstanding = Decimal(str(shares.get("outstanding_shares") or 0))
    nav_total = Decimal(str(nav_snapshot.get("nav_total_nok") or 0))
    if bought <= 0 or outstanding <= 0 or nav_total <= 0:
        return {"per_share_nok": None, "pct": None}
    actual = nav_total / outstanding
    without_program = (nav_total + spent) / (outstanding + bought)
    effect = actual - without_program
    return {
        "per_share_nok": round(float(effect), 4),
        "pct": round(float(effect / without_program * Decimal("100")), 4),
    }


def _share_count_nav_effect(
    start_snapshot, nav_snapshot, latest, shares
) -> float | None:
    """Reuse the NAV attribution's pure denominator effect for the active program."""
    if (
        start_snapshot is None
        or nav_snapshot is None
        or latest is None
        or shares is None
    ):
        return None
    bought = int(latest["cumulative_program_shares"] or 0)
    current_shares = int(shares["outstanding_shares"] or 0)
    if bought <= 0 or current_shares <= 0:
        return None
    driver = _share_count_driver(
        start_total_nok=Decimal(str(start_snapshot["nav_total_nok"])),
        current_total_nok=Decimal(str(nav_snapshot["nav_total_nok"])),
        start_shares=current_shares + bought,
        current_shares=current_shares,
    )
    return driver["per_share_nok"]


async def buyback_dashboard(
    repository,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    forecast = await buyback_forecast(repository, as_of_date=as_of_date)
    as_of = str(forecast.get("as_of_date") or as_of_date or date.today().isoformat())[
        :10
    ]

    latest = await repository.first(
        """
        SELECT b.period_start, b.trade_date, b.shares, b.avg_price_nok, b.amount_nok,
               b.cumulative_program_shares, b.cumulative_program_avg_price_nok,
               b.cumulative_program_amount_nok,
               b.treasury_shares_after, p.external_program_id, p.max_shares,
               p.max_price_nok, p.start_date, p.end_date
        FROM buybacks b JOIN buyback_programs p ON p.id=b.program_id
        WHERE b.trade_date <= ? AND p.status = 'ACTIVE'
          AND (p.start_date IS NULL OR p.start_date <= ?)
          AND (p.end_date IS NULL OR p.end_date >= ?)
        ORDER BY b.trade_date DESC, b.id DESC LIMIT 1
        """,
        (as_of, as_of, as_of),
    )
    share_count = await repository.first(
        """
        SELECT effective_from, total_shares, treasury_shares, outstanding_shares
        FROM otello_share_counts
        WHERE effective_from <= ?
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of,),
    )
    nav_snapshot = await repository.first(
        """
        SELECT nav_total_nok
        FROM nav_snapshots
        WHERE calculation_version = ?
          AND nav_scope = 'FULL'
          AND substr(as_of_at, 1, 10) <= ?
        ORDER BY as_of_at DESC, id DESC LIMIT 1
        """,
        (FULL_CALCULATION_VERSION, as_of),
    )
    start_nav_snapshot = None
    if latest is not None and latest.get("start_date"):
        start_nav_snapshot = await repository.first(
            """
            SELECT nav_total_nok
            FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = 'FULL'
              AND substr(as_of_at, 1, 10) <= ?
            ORDER BY as_of_at DESC, id DESC LIMIT 1
            """,
            (FULL_CALCULATION_VERSION, latest["start_date"]),
        )

    raw_history = list(forecast.get("recent_program_weeks") or [])
    volumes: dict[str, int] = {}
    if raw_history:
        start = min(str(item["period_start"]) for item in raw_history)
        end = max(str(item["period_end"]) for item in raw_history)
        rows = await repository.all(
            """
            SELECT ma.trading_date, ma.volume_shares
            FROM market_activity ma
            JOIN instruments i ON i.id=ma.instrument_id
            WHERE i.symbol='OTEC' AND ma.trading_date BETWEEN ? AND ? AND ma.volume_shares > 0
            ORDER BY ma.trading_date
            """,
            (start, end),
        )
        volumes = {str(row["trading_date"]): int(row["volume_shares"]) for row in rows}
    history = _enrich_history(raw_history, volumes)
    latest_metrics = await _latest_week_metrics(repository, latest)

    latest_payload = dict(latest) if latest is not None else None
    _normalize_latest_numeric_fields(latest_payload)
    if latest_payload is not None:
        latest_payload.update(latest_metrics)

    shares = None
    if share_count is not None or latest_payload is not None:
        total = int(share_count["total_shares"]) if share_count is not None else None
        reported_treasury = (
            int(share_count["treasury_shares"]) if share_count is not None else None
        )
        latest_treasury = (
            int(latest_payload["treasury_shares_after"])
            if latest_payload is not None
            and latest_payload.get("treasury_shares_after") is not None
            else None
        )
        use_latest = latest_treasury is not None and (
            share_count is None
            or str(latest_payload.get("trade_date") or "")
            >= str(share_count["effective_from"])
        )
        treasury = latest_treasury if use_latest else reported_treasury
        outstanding = (
            total - treasury
            if total is not None and treasury is not None
            else (
                int(share_count["outstanding_shares"])
                if share_count is not None
                else None
            )
        )
        shares = {
            "total_shares": total,
            "treasury_shares": treasury,
            "outstanding_shares": outstanding,
            "effective_from": (
                latest_payload.get("trade_date")
                if use_latest and latest_payload
                else (
                    share_count["effective_from"] if share_count is not None else None
                )
            ),
            "treasury_source": "LATEST_BUYBACK" if use_latest else "SHARE_COUNT",
        }

    program = forecast.get("program") or (latest_payload or {})
    max_shares = int(program.get("max_shares") or 0)
    cumulative = int(
        program.get("cumulative_shares")
        or (latest_payload or {}).get("cumulative_program_shares")
        or 0
    )
    remaining = max(0, max_shares - cumulative) if max_shares else 0
    cumulative_amount = Decimal(
        str((latest_payload or {}).get("cumulative_program_amount_nok") or 0)
    )
    vwap = cumulative_amount / cumulative if cumulative and cumulative_amount else None
    average_price = (latest_payload or {}).get("cumulative_program_avg_price_nok")
    if average_price is None and vwap is not None:
        average_price = str(vwap)
    program_end = program.get("end_date")
    program_summary = {
        **program,
        "max_shares": max_shares or None,
        "cumulative_shares": cumulative,
        "remaining_shares": remaining if max_shares else None,
        "average_purchase_price_nok": average_price,
        "vwap_nok": str(vwap) if vwap is not None else None,
        "progress_pct": (
            round(cumulative / max_shares * 100, 1) if max_shares else None
        ),
        "cash_spent_nok": -cumulative_amount if cumulative_amount else None,
        "share_count_nav_effect_per_share_nok": _share_count_nav_effect(
            start_nav_snapshot, nav_snapshot, latest, shares
        ),
    }

    return {
        "ready": latest_payload is not None,
        "status": forecast.get("status") or ("OK" if latest_payload else "NO_DATA"),
        "as_of_date": as_of,
        "program": program_summary,
        "latest_week": latest_payload,
        "shares": shares,
        "nav_effect": _nav_effect(nav_snapshot, latest, shares),
        "forecast": forecast,
        "backtest": {
            "metrics": forecast.get("active_program_backtest") or {"weeks": 0},
            "weeks": history,
        },
        "completion": _completion(
            forecast,
            history,
            remaining_shares=remaining,
            program_end_date=str(program_end) if program_end else None,
            latest_period_end=(
                str(latest_payload.get("trade_date")) if latest_payload else None
            ),
        ),
        "methodology_note": (
            "Volumandel viser Otellos faktiske kjøp som andel av faktisk OTEC-volum i hele uken. "
            "Dette er et investorforholdstall, ikke selve Safe Harbour-testen. 25 %-grensen vurderes "
            "per kjøpsdag mot gjennomsnittlig dagsvolum i de 20 foregående handelsdagene. "
            "Safe Harbour-kapasitet og neste-uke-prognose følger den eksisterende walk-forward-modellen."
        ),
    }
