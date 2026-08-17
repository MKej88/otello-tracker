from __future__ import annotations

from datetime import date
from typing import Any

from app.buybacks import (
    activity_check_done,
    ingest_previous_trading_day_activity,
    seed_otec_activity_history,
    sync_current_program_terms,
)
from app.db.migration_runner import init_database
from app.jobs.refresh_dashboard import run_refresh as run_core_refresh
from app.marketdata.euronext_delayed import download_euronext_delayed_equities


def _record_error(result: dict[str, Any], step: str, exc: Exception) -> None:
    result.setdefault("source_errors", []).append({"step": step, "error": str(exc)})
    if result.get("status") == "ok":
        result["status"] = "degraded"


def run_refresh(database_path: str, **kwargs: Any) -> dict[str, Any]:
    """Phase-13 wrapper around the established dashboard refresh.

    NAV behavior remains owned by the existing refresh pipeline. This wrapper adds the
    small, independent datasets needed by the buyback forecast and keeps those failures
    fail-soft so they can never prevent NAV from refreshing.
    """
    init_database(database_path)
    activity_seed = seed_otec_activity_history(database_path)
    result = run_core_refresh(database_path, **kwargs)
    result.setdefault("steps", {})["otec_activity_seed"] = activity_seed

    target = kwargs.get("target_date")
    today = date.today()
    target_day = date.fromisoformat(target) if target else today

    if target_day == today and today.weekday() < 5 and not activity_check_done(database_path):
        try:
            url, payload = download_euronext_delayed_equities("PREVIOUS_TRADING_DAY")
            activity = ingest_previous_trading_day_activity(
                payload,
                source_url=url,
                database_path=database_path,
                check_date=today.isoformat(),
            )
            result["steps"]["otec_previous_day_activity"] = activity
        except Exception as exc:
            _record_error(result, "otec_previous_day_activity", exc)
            result["steps"]["otec_previous_day_activity"] = None
    else:
        result["steps"]["otec_previous_day_activity"] = {
            "skipped": True,
            "reason": "already_checked_or_not_live_weekday",
        }

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
