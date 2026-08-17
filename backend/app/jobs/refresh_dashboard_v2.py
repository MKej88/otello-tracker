from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.buybacks import (
    activity_check_done,
    ingest_previous_trading_day_activity,
    market_activity_status,
    seed_otec_activity_history,
    sync_current_program_terms,
)
from app.db.migration_runner import init_database
from app.jobs.refresh_dashboard import run_refresh as run_core_refresh
from app.marketdata.euronext_delayed import download_euronext_delayed_equities
from app.marketdata.oslo_calendar import is_oslo_bors_trading_day
from app.marketdata.otec_feed import finalize_otec_eod_from_payload, refresh_otec_intraday_price


def _record_error(result: dict[str, Any], step: str, exc: Exception) -> None:
    result.setdefault("source_errors", []).append({"step": step, "error": str(exc)})
    if result.get("status") == "ok":
        result["status"] = "degraded"


def _previous_oslo_trading_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_oslo_bors_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def run_refresh(database_path: str, **kwargs: Any) -> dict[str, Any]:
    """Hardened wrapper around the established dashboard refresh.

    Lightweight OTEC and previous-session EOD inputs are collected *before* the core
    rebuild so the resulting NAV snapshots immediately use the freshest price data.
    The legacy core refresh is explicitly prevented from downloading the full current-day
    Euronext trade file merely to obtain an intraday OTEC price.
    """
    init_database(database_path)
    target = kwargs.get("target_date")
    today = date.today()
    target_day = date.fromisoformat(target) if target else today
    requested_live_otec = bool(kwargs.get("fetch_otec_delayed", True))

    pre_steps: dict[str, Any] = {}
    pre_errors: list[dict[str, str]] = []

    existing_activity = market_activity_status(database_path)
    if existing_activity["status"] == "empty" or (existing_activity.get("count") or 0) < 500:
        pre_steps["otec_activity_seed"] = seed_otec_activity_history(database_path)
    else:
        pre_steps["otec_activity_seed"] = {
            "skipped": True,
            "reason": "historical_activity_already_seeded",
            "count": existing_activity["count"],
            "to": existing_activity["to"],
        }

    if requested_live_otec and target_day == today:
        try:
            pre_steps["otec_delayed"] = refresh_otec_intraday_price(database_path)
        except Exception as exc:
            pre_errors.append({"step": "otec_delayed", "error": str(exc)})
            pre_steps["otec_delayed"] = None
    elif requested_live_otec:
        pre_steps["otec_delayed"] = {
            "skipped": True,
            "reason": "live_source_not_used_for_historical_target",
        }
    else:
        pre_steps["otec_delayed"] = {"skipped": True}

    if target_day == today and today.weekday() < 5 and not activity_check_done(database_path):
        try:
            url, payload = download_euronext_delayed_equities("PREVIOUS_TRADING_DAY")
            activity = ingest_previous_trading_day_activity(
                payload,
                source_url=url,
                database_path=database_path,
                check_date=today.isoformat(),
            )
            prior_eod = finalize_otec_eod_from_payload(
                payload,
                source_url=url,
                target_date=_previous_oslo_trading_day(today).isoformat(),
                database_path=database_path,
                source_selection="PREVIOUS_TRADING_DAY",
            )
            pre_steps["otec_previous_day_activity"] = {
                "activity": activity,
                "eod_price": prior_eod,
            }
        except Exception as exc:
            pre_errors.append({"step": "otec_previous_day_activity", "error": str(exc)})
            pre_steps["otec_previous_day_activity"] = None
    else:
        pre_steps["otec_previous_day_activity"] = {
            "skipped": True,
            "reason": "already_checked_or_not_live_weekday",
        }

    core_kwargs = dict(kwargs)
    core_kwargs["fetch_otec_delayed"] = False
    result = run_core_refresh(database_path, **core_kwargs)
    result.setdefault("steps", {}).update(pre_steps)
    if pre_errors:
        result.setdefault("source_errors", []).extend(pre_errors)
        if result.get("status") == "ok":
            result["status"] = "degraded"

    if kwargs.get("fetch_buybacks", True):
        try:
            result["steps"]["buyback_program_terms"] = sync_current_program_terms(
                database_path,
                to_date=target_day.isoformat(),
            )
        except Exception as exc:
            _record_error(result, "buyback_program_terms", exc)
            result["steps"]["buyback_program_terms"] = None
    else:
        result["steps"]["buyback_program_terms"] = {"skipped": True}

    return result
