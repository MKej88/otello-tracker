from __future__ import annotations

import argparse
import json

from app.buybacks import buyback_status, collect_recent_buybacks
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.nav import daily_cash_status, daily_nav_status, rebuild_daily_cash, rebuild_daily_core_nav
from app.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect recent Otello buybacks from public Euronext pages")
    parser.add_argument("--database", default=settings.database_path)
    parser.add_argument(
        "--rebuild-nav",
        action="store_true",
        help="Rebuild daily cash/NAV after ingesting new buybacks",
    )
    args = parser.parse_args()

    init_database(args.database)
    seed_curated_history(args.database)
    collection = collect_recent_buybacks(args.database)

    result: dict = {
        "collection": collection,
        "buyback_status": buyback_status(args.database),
    }
    if args.rebuild_nav and collection["ingested"]:
        result["cash_rebuild"] = rebuild_daily_cash(args.database)
        result["nav_rebuild"] = rebuild_daily_core_nav(args.database)
        result["cash_status"] = daily_cash_status(args.database)
        result["nav_status"] = daily_nav_status(args.database)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
