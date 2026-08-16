from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from app.buybacks import buyback_status, collect_recent_buybacks
from app.dashboard import dashboard_summary
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.marketdata.b3_cotahist import download_cotahist_year
from app.marketdata.backfill import (
    import_b3_bmob3_zip,
    import_ecb_fx_csv,
    import_euronext_otec_csv,
    import_investing_otec_csv,
    market_data_status,
)
from app.marketdata.ecb_fx import fetch_ecb_csv
from app.nav import (
    daily_cash_status,
    daily_nav_status,
    full_nav_status,
    other_net_assets_status,
    rebuild_core_nav_anchors,
    rebuild_daily_cash,
    rebuild_daily_core_nav,
    rebuild_daily_full_nav,
    rebuild_daily_other_net_assets,
    rebuild_other_net_assets_anchors,
)
from app.settings import settings


def _safe_step(name: str, fn: Callable[[], Any], errors: list[dict[str, str]]) -> Any:
    try:
        return fn()
    except Exception as exc:  # network/provider errors must not block later rebuilds
        errors.append({"step": name, "error": str(exc)})
        return None


def _staleness(summary: dict[str, Any], target_date: str) -> dict[str, Any]:
    as_of = summary.get("as_of_date")
    if not as_of:
        return {"calendar_days": None, "stale": True}
    delta = (date.fromisoformat(target_date) - date.fromisoformat(as_of)).days
    return {"calendar_days": max(delta, 0), "stale": delta > 3}


def run_refresh(
    database_path: str,
    *,
    target_date: str | None = None,
    fx_lookback_days: int = 14,
    b3_year: int | None = None,
    fetch_ecb: bool = True,
    fetch_b3: bool = True,
    fetch_buybacks: bool = True,
    otec_euronext_csv: str | None = None,
    otec_investing_csv: str | None = None,
) -> dict[str, Any]:
    """Refresh automatable inputs and rebuild both CORE and FULL NAV.

    Provider failures are recorded per step. Persisted data is still used to rebuild
    later model layers, so a temporary upstream outage degrades the result rather than
    destroying the dashboard. FULL NAV remains a separate snapshot series and never
    overwrites CORE.
    """
    end = target_date or date.today().isoformat()
    end_day = date.fromisoformat(end)
    year = b3_year or end_day.year
    fx_start = (end_day - timedelta(days=max(2, fx_lookback_days))).isoformat()

    init_database(database_path)
    history = seed_curated_history(database_path)
    errors: list[dict[str, str]] = []
    steps: dict[str, Any] = {"history_manifest": history.get("manifest_version")}

    if fetch_ecb:
        def update_ecb() -> dict[str, Any]:
            url, text = fetch_ecb_csv(fx_start, end)
            return {
                "rows_written": import_ecb_fx_csv(text, source_url=url, database_path=database_path),
                "from": fx_start,
                "to": end,
            }
        steps["ecb"] = _safe_step("ecb", update_ecb, errors)
    else:
        steps["ecb"] = {"skipped": True}

    if fetch_b3:
        def update_b3() -> dict[str, Any]:
            payload = download_cotahist_year(year)
            return {
                "year": year,
                "rows_written": import_b3_bmob3_zip(payload, year=year, database_path=database_path),
            }
        steps["b3"] = _safe_step("b3", update_b3, errors)
    else:
        steps["b3"] = {"skipped": True}

    if otec_euronext_csv:
        def update_otec_euronext() -> dict[str, Any]:
            text = Path(otec_euronext_csv).read_text(encoding="utf-8-sig")
            return {
                "rows_written": import_euronext_otec_csv(text, database_path=database_path),
                "path": otec_euronext_csv,
            }
        steps["otec_euronext"] = _safe_step("otec_euronext", update_otec_euronext, errors)

    if otec_investing_csv:
        def update_otec_investing() -> Any:
            text = Path(otec_investing_csv).read_text(encoding="utf-8-sig")
            return import_investing_otec_csv(text, database_path=database_path)
        steps["otec_investing"] = _safe_step("otec_investing", update_otec_investing, errors)

    if fetch_buybacks:
        steps["buybacks"] = _safe_step(
            "buybacks", lambda: collect_recent_buybacks(database_path), errors
        )
    else:
        steps["buybacks"] = {"skipped": True}

    # Rebuild from persisted inputs even when an upstream provider was temporarily down.
    steps["core_anchors"] = _safe_step(
        "core_anchors", lambda: rebuild_core_nav_anchors(database_path), errors
    )
    steps["daily_cash"] = _safe_step(
        "daily_cash", lambda: rebuild_daily_cash(database_path, end_date=end), errors
    )
    # Preserve the Phase 8 public step name for backwards compatibility.
    steps["daily_nav"] = _safe_step(
        "daily_nav", lambda: rebuild_daily_core_nav(database_path, end_date=end), errors
    )
    steps["other_net_assets_anchors"] = _safe_step(
        "other_net_assets_anchors", lambda: rebuild_other_net_assets_anchors(database_path), errors
    )
    steps["daily_other_net_assets"] = _safe_step(
        "daily_other_net_assets", lambda: rebuild_daily_other_net_assets(database_path, end_date=end), errors
    )
    steps["daily_full_nav"] = _safe_step(
        "daily_full_nav", lambda: rebuild_daily_full_nav(database_path, end_date=end), errors
    )

    summary = dashboard_summary(database_path)
    stale = _staleness(summary, end)
    status = "ok"
    if not summary.get("ready"):
        status = "not_ready"
    elif errors or stale["stale"] or summary.get("data_status") == "DEGRADED":
        status = "degraded"

    return {
        "status": status,
        "target_date": end,
        "steps": steps,
        "source_errors": errors,
        "staleness": stale,
        "market_data": market_data_status(database_path),
        "buyback_status": buyback_status(database_path),
        "cash_status": daily_cash_status(database_path),
        "core_nav_status": daily_nav_status(database_path),
        "other_net_assets_status": other_net_assets_status(database_path),
        "full_nav_status": full_nav_status(database_path),
        "dashboard": summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh Otello dashboard data and rebuild NAV")
    parser.add_argument("--database", default=settings.database_path)
    parser.add_argument("--date", default=None, help="Target date, defaults to today")
    parser.add_argument("--fx-lookback-days", type=int, default=14)
    parser.add_argument("--b3-year", type=int, default=None, help="Defaults to target-date year")
    parser.add_argument("--skip-ecb", action="store_true")
    parser.add_argument("--skip-b3", action="store_true")
    parser.add_argument("--skip-buybacks", action="store_true")
    parser.add_argument("--otec-csv", default=None, help="Optional fresh Euronext OTEC CSV")
    parser.add_argument("--otec-investing-csv", default=None, help="Optional Investing OTEC CSV")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless refresh status is ok")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_refresh(
        args.database,
        target_date=args.date,
        fx_lookback_days=args.fx_lookback_days,
        b3_year=args.b3_year,
        fetch_ecb=not args.skip_ecb,
        fetch_b3=not args.skip_b3,
        fetch_buybacks=not args.skip_buybacks,
        otec_euronext_csv=args.otec_csv,
        otec_investing_csv=args.otec_investing_csv,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if args.strict and result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
