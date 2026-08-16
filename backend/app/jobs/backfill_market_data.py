from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.marketdata.b3_cotahist import download_cotahist_year
from app.marketdata.backfill import (
    import_b3_bmob3_file,
    import_b3_bmob3_zip,
    import_ecb_fx_csv,
    import_euronext_otec_csv,
    import_investing_otec_csv,
    market_data_status,
)
from app.marketdata.ecb_fx import fetch_ecb_csv
from app.nav import rebuild_core_nav_anchors
from app.settings import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill market data for Otello NAV Dashboard")
    parser.add_argument("--database", default=settings.database_path)
    parser.add_argument("--start", default="2021-02-10", help="ECB start date")
    parser.add_argument("--end", default=None, help="ECB end date")
    parser.add_argument("--ecb", action="store_true", help="Fetch ECB FX history")
    parser.add_argument("--b3-year", type=int, action="append", default=[], help="Download/import B3 COTAHIST year")
    parser.add_argument(
        "--b3-file",
        action="append",
        default=[],
        metavar="YEAR:PATH",
        help="Import a manually downloaded B3 COTAHIST ZIP",
    )
    parser.add_argument("--otec-csv", default=None, help="Import Euronext OTEC historical CSV")
    parser.add_argument("--otec-date-order", default="DMY", choices=["DMY", "MDY", "YMD"])
    parser.add_argument(
        "--otec-investing-csv",
        default=None,
        help="Import manually exported Investing.com OTEC CSV; reverses the 2022 dividend adjustment",
    )
    parser.add_argument("--rebuild-nav", action="store_true", help="Rebuild report-date CORE NAV anchors")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    init_database(args.database)
    seed_curated_history(args.database)
    results: dict[str, object] = {}

    if args.ecb:
        url, text = fetch_ecb_csv(args.start, args.end)
        results["ecb_rows_written"] = import_ecb_fx_csv(
            text, source_url=url, database_path=args.database
        )

    for year in args.b3_year:
        payload = download_cotahist_year(year)
        results[f"b3_{year}_rows_written"] = import_b3_bmob3_zip(
            payload, year=year, database_path=args.database
        )

    for spec in args.b3_file:
        try:
            year_text, path_text = spec.split(":", 1)
            year = int(year_text)
        except ValueError as exc:
            raise SystemExit("--b3-file må være YEAR:PATH") from exc
        results[f"b3_{year}_rows_written"] = import_b3_bmob3_file(
            Path(path_text), year=year, database_path=args.database
        )

    if args.otec_csv:
        text = Path(args.otec_csv).read_text(encoding="utf-8-sig")
        results["otec_euronext_rows_written"] = import_euronext_otec_csv(
            text,
            date_order=args.otec_date_order,
            database_path=args.database,
        )

    if args.otec_investing_csv:
        text = Path(args.otec_investing_csv).read_text(encoding="utf-8-sig")
        results["otec_investing"] = import_investing_otec_csv(
            text,
            database_path=args.database,
        )

    if args.rebuild_nav:
        results["core_nav"] = rebuild_core_nav_anchors(args.database)

    results["market_data_status"] = market_data_status(args.database)
    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
