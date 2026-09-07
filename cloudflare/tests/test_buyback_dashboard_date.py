from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from buyback_dashboard import buyback_dashboard  # noqa: E402


class _UtcDate(date):
    @classmethod
    def today(cls) -> date:
        return cls(2026, 1, 15)


class _Repository:
    def __init__(self) -> None:
        self.dashboard_latest_parameters: tuple[Any, ...] | None = None

    async def first(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        if "SELECT p.id" in sql:
            return {
                "id": 1,
                "external_program_id": "program-2026",
                "start_date": "2026-01-16",
                "end_date": "2026-12-31",
                "status": "ACTIVE",
                "max_shares": 1_000_000,
                "max_price_nok": 30,
                "latest_period_end": "2026-01-09",
                "cumulative_program_shares": 100_000,
                "treasury_shares_after": 100_000,
            }
        if "SELECT b.period_start" in sql:
            self.dashboard_latest_parameters = parameters
        return None

    async def all(
        self, _sql: str, _parameters: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        return []


def test_dashboard_keeps_oslo_date_when_forecast_returns_early() -> None:
    repository = _Repository()

    with (
        patch("buyback_service._oslo_today", return_value=date(2026, 1, 16)),
        patch("buyback_dashboard.date", _UtcDate),
    ):
        result = asyncio.run(buyback_dashboard(repository))

    assert result["forecast"]["status"] == "INSUFFICIENT_VOLUME_HISTORY"
    assert repository.dashboard_latest_parameters == (
        "2026-01-16",
        "2026-01-16",
        "2026-01-16",
    )
