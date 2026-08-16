from __future__ import annotations

import argparse
import json

from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.nav import daily_cash_status, daily_nav_status, rebuild_daily_cash, rebuild_daily_core_nav
from app.settings import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild anchored daily Otello CORE NAV")
    parser.add_argument("--database", default=settings.database_path)
    parser.add_argument("--start", default=None, help="Optional first OTEC trading date")
    parser.add_argument("--end", default=None, help="Optional final date; defaults to latest market-data date")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    init_database(args.database)
    seed_curated_history(args.database)

    cash_result = rebuild_daily_cash(args.database, end_date=args.end)
    nav_result = rebuild_daily_core_nav(
        args.database,
        start_date=args.start,
        end_date=args.end,
    )
    print(
        json.dumps(
            {
                "cash_rebuild": cash_result,
                "nav_rebuild": nav_result,
                "cash_status": daily_cash_status(args.database),
                "nav_status": daily_nav_status(args.database),
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
