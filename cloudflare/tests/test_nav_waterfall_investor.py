from __future__ import annotations

import asyncio
from decimal import Decimal

from src.nav_waterfall_investor import _cash_breakdown


def test_daily_buybacks_supersede_matching_weekly_total() -> None:
    class Repository:
        async def all(
            self, sql: str, parameters: tuple[str, str]
        ) -> list[dict[str, object]]:
            assert "FROM cash_movements" in sql
            assert parameters == ("2026-08-01", "2026-08-09")
            return [
                {
                    "movement_date": "2026-08-07",
                    "movement_type": "OTELLO_BUYBACK",
                    "amount_nok": "-2000",
                    "description": (
                        "Otello buyback: 100 shares during 2026-08-03–2026-08-07."
                    ),
                    "external_movement_id": None,
                    "buyback_id": 42,
                },
                {
                    "movement_date": "2026-08-05",
                    "movement_type": "OTELLO_BUYBACK_DAILY",
                    "amount_nok": "-800",
                    "description": "Daglig tilbakekjøp",
                    "external_movement_id": None,
                    "buyback_id": 42,
                },
                {
                    "movement_date": "2026-08-06",
                    "movement_type": "OTELLO_BUYBACK_DAILY",
                    "amount_nok": "-1200",
                    "description": "Daglig tilbakekjøp",
                    "external_movement_id": None,
                    "buyback_id": 42,
                },
            ]

    result = asyncio.run(
        _cash_breakdown(
            Repository(),
            anchor_date="2026-08-01",
            as_of_date="2026-08-09",
        )
    )

    assert result["buyback_cash_nok"] == Decimal("-2000")
    assert result["buyback_metadata"] == {
        "weekly_cash_rows": 0,
        "daily_cash_rows": 2,
        "weekly_superseded": 1,
        "movement_count": 2,
        "cross_anchor_excluded": 0,
        "source_mode": "DAILY_WHEN_AVAILABLE_WEEKLY_FALLBACK",
    }
