from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Callable

from app.buybacks import (
    activity_check_done,
    ingest_previous_trading_day_activity,
    market_activity_status,
    seed_otec_activity_history,
    sync_current_program_terms,
)
from app.dashboard import dashboard_summary
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.marketdata.bmob3_feed import maybe_finalize_bmob3_eod, refresh_bmob3_intraday_price
from app.marketdata.euronext_delayed import download_euronext_delayed_equities
from app.marketdata.oslo_calendar import is_oslo_bors_trading_day
from app.marketdata.otec_feed import (
    finalize_otec_eod_from_payload,
    maybe_finalize_otec_eod,
    refresh_otec_intraday_price,
)
from app.nav import rebuild_daily_cash, rebuild_daily_core_nav, rebuild_daily_full_nav
from app.newsweb import (
    collect_newsweb_buybacks,
    collect_newsweb_history,
    sync_newsweb_daily_buyback_cash,
)


def _safe_step(name: str, fn: Callable[[], Any], errors: list[dict[str, str]]) -> Any:
    try:
        return fn()
    except Exception as exc:
        errors.append({"step": name, "error": str(exc)})
        return None


def _latest_otec_date(database_path: str, target_date: str) -> str | None:
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT MAX(mp.trading_date) AS d
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            WHERE i.symbol='OTEC' AND mp.price_type IN ('CLOSE','LAST')
              AND mp.trading_date <= ?
            """,
            (target_date,),
        ).fetchone()
    return row["d"] if row and row["d"] else None


def _previous_oslo_trading_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_oslo_bors_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def _eod_is_authoritative_for_cycle(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") in {"ok", "no_trade"}:
        return True
    return result.get("status") == "skipped" and result.get("reason") == "eod_already_finalized"


def run_fast_refresh(
    database_path: str,
    *,
    target_date: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh only sources/layers that can matter intraday.

    Heavy annual/history providers (B3 COTAHIST, ECB, CVM and MFN fallback) deliberately
    live in the daily full refresh. OTEC uses Euronext's small delayed trade windows while
    BMOB3 uses B3's lightweight public delayed web quote. Each market has a separate EOD
    finalization so the latest LAST is available before the next official daily CLOSE.
    """
    end = target_date or date.today().isoformat()
    end_day = date.fromisoformat(end)
    today = date.today()
    init_database(database_path)
    seed_curated_history(database_path)

    errors: list[dict[str, str]] = []
    steps: dict[str, Any] = {}

    activity = market_activity_status(database_path)
    if activity.get("status") == "empty" or int(activity.get("count") or 0) < 500:
        steps["otec_activity_seed"] = _safe_step(
            "otec_activity_seed",
            lambda: seed_otec_activity_history(database_path),
            errors,
        )
    else:
        steps["otec_activity_seed"] = {
            "skipped": True,
            "reason": "historical_activity_already_seeded",
            "count": activity.get("count"),
            "to": activity.get("to"),
        }

    if end_day == today:
        eod_result = _safe_step(
            "otec_eod",
            lambda: maybe_finalize_otec_eod(
                database_path,
                target_date=end,
                now=now,
            ),
            errors,
        )
        steps["otec_eod"] = eod_result
        if _eod_is_authoritative_for_cycle(eod_result):
            steps["otec_delayed"] = {
                "skipped": True,
                "reason": "eod_finalized_for_session",
            }
        else:
            steps["otec_delayed"] = _safe_step(
                "otec_delayed",
                lambda: refresh_otec_intraday_price(database_path, now=now),
                errors,
            )

        bmob3_eod = _safe_step(
            "bmob3_eod",
            lambda: maybe_finalize_bmob3_eod(database_path, now=now),
            errors,
        )
        steps["bmob3_eod"] = bmob3_eod
        if _eod_is_authoritative_for_cycle(bmob3_eod):
            steps["bmob3_delayed"] = {
                "skipped": True,
                "reason": "eod_finalized_for_session",
            }
        else:
            steps["bmob3_delayed"] = _safe_step(
                "bmob3_delayed",
                lambda: refresh_bmob3_intraday_price(database_path, now=now),
                errors,
            )
    else:
        steps["otec_delayed"] = {
            "skipped": True,
            "reason": "live_source_not_used_for_historical_target",
        }
        steps["otec_eod"] = {
            "skipped": True,
            "reason": "live_source_not_used_for_historical_target",
        }
        steps["bmob3_delayed"] = {
            "skipped": True,
            "reason": "live_source_not_used_for_historical_target",
        }
        steps["bmob3_eod"] = {
            "skipped": True,
            "reason": "live_source_not_used_for_historical_target",
        }

    if end_day == today and today.weekday() < 5 and not activity_check_done(database_path):
        def previous_activity() -> Any:
            url, payload = download_euronext_delayed_equities("PREVIOUS_TRADING_DAY")
            activity_result = ingest_previous_trading_day_activity(
                payload,
                source_url=url,
                database_path=database_path,
                check_date=today.isoformat(),
            )
            # Reuse the same complete Euronext payload to finalize yesterday's price.
            # This catches days where the Pi was offline at the same-day EOD checkpoint
            # without issuing another large download.
            previous_day = _previous_oslo_trading_day(today).isoformat()
            eod_result = finalize_otec_eod_from_payload(
                payload,
                source_url=url,
                target_date=previous_day,
                database_path=database_path,
                source_selection="PREVIOUS_TRADING_DAY",
            )
            return {"activity": activity_result, "eod_price": eod_result}

        steps["otec_previous_day_activity"] = _safe_step(
            "otec_previous_day_activity", previous_activity, errors
        )
    else:
        steps["otec_previous_day_activity"] = {
            "skipped": True,
            "reason": "already_checked_or_not_live_weekday",
        }

    history = _safe_step(
        "newsweb_history",
        lambda: collect_newsweb_history(database_path, to_date=end),
        errors,
    )
    steps["newsweb_history"] = history
    if isinstance(history, dict) and history.get("errors"):
        errors.append(
            {
                "step": "newsweb_history_partial",
                "error": json.dumps(history["errors"], ensure_ascii=False, default=str),
            }
        )

    buybacks = _safe_step(
        "newsweb_buybacks",
        # No explicit from_date: after the initial backfill the collector automatically
        # uses the latest daily transaction minus a 21-day safety overlap.
        lambda: collect_newsweb_buybacks(database_path, to_date=end),
        errors,
    )
    steps["newsweb_buybacks"] = buybacks
    if isinstance(buybacks, dict) and buybacks.get("errors"):
        errors.append(
            {
                "step": "newsweb_buybacks_partial",
                "error": json.dumps(buybacks["errors"], ensure_ascii=False, default=str),
            }
        )

    steps["newsweb_buyback_cash"] = _safe_step(
        "newsweb_buyback_cash",
        lambda: sync_newsweb_daily_buyback_cash(database_path),
        errors,
    )
    steps["buyback_program_terms"] = _safe_step(
        "buyback_program_terms",
        lambda: sync_current_program_terms(database_path, to_date=end),
        errors,
    )

    # Cash depends on the complete anchor chain, so it is rebuilt deterministically.
    # The expensive market/ONA history is not: CORE/FULL are refreshed only for the
    # freshest available OTEC trading date. FULL simply remains on its prior date if the
    # daily ONA layer has not yet been extended by the daily full refresh.
    steps["daily_cash"] = _safe_step(
        "daily_cash", lambda: rebuild_daily_cash(database_path, end_date=end), errors
    )
    latest_market_date = _latest_otec_date(database_path, end)
    if latest_market_date:
        steps["daily_nav"] = _safe_step(
            "daily_nav",
            lambda: rebuild_daily_core_nav(
                database_path,
                start_date=latest_market_date,
                end_date=latest_market_date,
            ),
            errors,
        )
        steps["daily_full_nav"] = _safe_step(
            "daily_full_nav",
            lambda: rebuild_daily_full_nav(
                database_path,
                start_date=latest_market_date,
                end_date=latest_market_date,
            ),
            errors,
        )
    else:
        steps["daily_nav"] = {"skipped": True, "reason": "no_otec_market_date"}
        steps["daily_full_nav"] = {"skipped": True, "reason": "no_otec_market_date"}

    summary = dashboard_summary(database_path)
    if not summary.get("ready"):
        status = "not_ready"
    elif errors or summary.get("data_status") in {"DEGRADED", "ESTIMATED"}:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "refresh_mode": "fast",
        "target_date": end,
        "latest_market_date": latest_market_date,
        "steps": steps,
        "source_errors": errors,
        "dashboard": summary,
    }
