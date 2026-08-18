from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Callable

from app.buybacks import seed_otec_activity_history
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.jobs.preflight import HISTORY_START, run_preflight
from app.jobs.refresh_dashboard import run_refresh
from app.marketdata.b3_cotahist import download_cotahist_year
from app.marketdata.backfill import (
    import_b3_bmob3_zip,
    import_ecb_fx_csv,
    import_euronext_otec_csv,
    import_investing_otec_csv,
)
from app.marketdata.ecb_fx import fetch_ecb_csv
from app.settings import settings

B3_START_YEAR = 2021


def _step(name: str, fn: Callable[[], Any], steps: dict[str, Any], errors: list[dict[str, str]]) -> Any:
    try:
        value = fn()
        steps[name] = value
        return value
    except Exception as exc:
        errors.append({"step": name, "error": str(exc)})
        steps[name] = {"status": "error", "error": str(exc)}
        return None


def run_bootstrap(
    database_path: str,
    *,
    target_date: str | None = None,
    history_start: str = HISTORY_START,
    b3_start_year: int = B3_START_YEAR,
    otec_euronext_csv: str | None = None,
    otec_investing_csv: str | None = None,
    otec_date_order: str = "DMY",
    fetch_network: bool = True,
) -> dict[str, Any]:
    """Build a production database from a clean file and finish with strict preflight.

    Historical OTEC prices are deliberately not scraped. Supply either the validated
    Euronext history CSV or the user's manual Investing.com export when bootstrapping a
    clean DB. The compact official OTEC activity history used by the buyback forecast is
    repository-curated and is always seeded so a clean production build cannot silently
    omit the forecast's 20-trading-day volume input.
    """
    target = date.fromisoformat(target_date) if target_date else date.today()
    steps: dict[str, Any] = {}
    errors: list[dict[str, str]] = []

    database_file = Path(database_path)
    if database_path != ":memory:":
        database_file.parent.mkdir(parents=True, exist_ok=True)

    steps["migrations_applied"] = init_database(database_path)
    history = seed_curated_history(database_path)
    steps["history_manifest"] = history.get("manifest_version")
    steps["otec_activity_history"] = seed_otec_activity_history(database_path)

    if fetch_network:
        def full_ecb() -> dict[str, Any]:
            url, text = fetch_ecb_csv(history_start, target.isoformat())
            return {
                "from": history_start,
                "to": target.isoformat(),
                "rows_written": import_ecb_fx_csv(text, source_url=url, database_path=database_path),
            }

        _step("ecb_full_history", full_ecb, steps, errors)

        for year in range(b3_start_year, target.year + 1):
            def load_year(year_value: int = year) -> dict[str, Any]:
                payload = download_cotahist_year(year_value)
                return {
                    "year": year_value,
                    "rows_written": import_b3_bmob3_zip(
                        payload, year=year_value, database_path=database_path
                    ),
                }

            _step(f"b3_{year}", load_year, steps, errors)
    else:
        steps["ecb_full_history"] = {"skipped": True, "reason": "network_disabled"}
        steps["b3_history"] = {"skipped": True, "reason": "network_disabled"}

    if otec_euronext_csv:
        def import_euronext() -> dict[str, Any]:
            path = Path(otec_euronext_csv)
            text = path.read_text(encoding="utf-8-sig")
            return {
                "path": str(path),
                "rows_written": import_euronext_otec_csv(
                    text,
                    date_order=otec_date_order,
                    database_path=database_path,
                ),
            }

        _step("otec_euronext_history", import_euronext, steps, errors)

    if otec_investing_csv:
        def import_investing() -> Any:
            path = Path(otec_investing_csv)
            text = path.read_text(encoding="utf-8-sig")
            return import_investing_otec_csv(text, database_path=database_path)

        _step("otec_investing_history", import_investing, steps, errors)

    if fetch_network:
        refresh = _step(
            "refresh_and_rebuild",
            lambda: run_refresh(
                database_path,
                target_date=target.isoformat(),
                fetch_ecb=False,
                fetch_b3=False,
                fetch_otec_delayed=True,
                fetch_buybacks=True,
                fetch_bemobi_news=True,
            ),
            steps,
            errors,
        )
    else:
        refresh = None
        steps["refresh_and_rebuild"] = {"skipped": True, "reason": "network_disabled"}

    preflight = run_preflight(
        database_path,
        target_date=target.isoformat(),
        history_start=history_start,
        check_derived=fetch_network,
    )
    steps["preflight"] = preflight

    if not otec_euronext_csv and not otec_investing_csv:
        otec_blocker = next(
            (
                item for item in preflight.get("blockers", [])
                if item.get("name") == "otec_historical_prices"
            ),
            None,
        )
        if otec_blocker:
            errors.append(
                {
                    "step": "otec_historical_prices",
                    "error": (
                        "Clean bootstrap needs historical OTEC prices. Re-run with "
                        "--otec-csv PATH or --otec-investing-csv PATH, or copy a previously "
                        "validated production database before running preflight."
                    ),
                }
            )

    ready = bool(preflight.get("ready")) and not any(
        item.get("step") in {"ecb_full_history", "refresh_and_rebuild"} for item in errors
    )
    return {
        "status": "READY" if ready else "NOT_READY",
        "ready": ready,
        "database": database_path,
        "target_date": target.isoformat(),
        "history_start": history_start,
        "steps": steps,
        "errors": errors,
        "refresh_status": refresh.get("status") if isinstance(refresh, dict) else None,
        "next_action": None if ready else "Resolve preflight blockers, then run preflight --strict again.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap a clean Otello production database")
    parser.add_argument("--database", default=settings.database_path)
    parser.add_argument("--date", default=None, help="Target date; defaults to today")
    parser.add_argument("--history-start", default=HISTORY_START)
    parser.add_argument("--b3-start-year", type=int, default=B3_START_YEAR)
    parser.add_argument("--otec-csv", default=None, help="Validated Euronext historical OTEC CSV")
    parser.add_argument(
        "--otec-investing-csv",
        default=None,
        help="Manual Investing.com OTEC export; historical dividend adjustment is reconstructed",
    )
    parser.add_argument("--otec-date-order", default="DMY", choices=["DMY", "MDY", "YMD"])
    parser.add_argument("--no-network", action="store_true", help="Seed/migrate only; useful for diagnostics/tests")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless production preflight passes")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_bootstrap(
        args.database,
        target_date=args.date,
        history_start=args.history_start,
        b3_start_year=args.b3_start_year,
        otec_euronext_csv=args.otec_csv,
        otec_investing_csv=args.otec_investing_csv,
        otec_date_order=args.otec_date_order,
        fetch_network=not args.no_network,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if args.strict and not result["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
