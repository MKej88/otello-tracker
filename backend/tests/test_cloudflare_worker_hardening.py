from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.buyback_service import METHOD_VERSION, buyback_forecast  # noqa: E402


class CountingRepository:
    def __init__(self) -> None:
        self.query_count = 0

    async def first(self, sql: str, parameters=()):
        self.query_count += 1
        if "FROM buybacks b JOIN buyback_programs" in sql:
            return {
                "id": 1,
                "external_program_id": "QUERY-BUDGET",
                "start_date": "2026-06-01",
                "end_date": "2026-09-30",
                "status": "ACTIVE",
                "max_shares": 1_000_000,
                "max_price_nok": "20.00",
                "latest_period_end": "2026-08-14",
                "cumulative_program_shares": 100_000,
                "treasury_shares_after": 5_100_000,
            }
        raise AssertionError(f"Unexpected first query: {sql}")

    async def all(self, sql: str, parameters=()):
        self.query_count += 1
        if "FROM market_activity" in sql:
            start = date(2026, 6, 29)
            rows = []
            current = start
            while current <= date(2026, 8, 14):
                if current.weekday() < 5:
                    rows.append(
                        {
                            "trading_date": current.isoformat(),
                            "volume_shares": 100_000,
                            "last_price_nok": "17.00",
                            "quality": "HISTORICAL_EXPORT",
                        }
                    )
                current += timedelta(days=1)
            return rows
        if "FROM buybacks b" in sql and "b.program_id=?" in sql:
            return [
                {
                    "period_start": "2026-08-10",
                    "trade_date": "2026-08-14",
                    "shares": 50_000,
                    "cumulative_program_shares": 100_000,
                }
            ]
        raise AssertionError(f"Unexpected all query: {sql}")


def test_buyback_forecast_uses_constant_small_d1_query_budget() -> None:
    repository = CountingRepository()
    result = asyncio.run(buyback_forecast(repository, as_of_date="2026-08-17"))

    assert result["ready"] is True
    assert result["methodology_version"] == METHOD_VERSION
    assert repository.query_count == 3
