from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from buyback_dashboard import buyback_dashboard  # noqa: E402


class _ConcurrentReadRepository:
    def __init__(self) -> None:
        self.started_reads = 0
        self.all_reads_started = asyncio.Event()

    async def first(
        self, _sql: str, _parameters: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        self.started_reads += 1
        if self.started_reads == 3:
            self.all_reads_started.set()
        await asyncio.wait_for(self.all_reads_started.wait(), timeout=1.0)
        return None

    async def all(
        self, _sql: str, _parameters: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        return []


def test_independent_buyback_dashboard_reads_start_in_parallel() -> None:
    repository = _ConcurrentReadRepository()
    forecast = {
        "as_of_date": "2026-09-26",
        "status": "NO_DATA",
        "recent_program_weeks": [],
    }

    with patch("buyback_dashboard.buyback_forecast", return_value=forecast):
        result = asyncio.run(buyback_dashboard(repository))

    assert repository.started_reads == 3
    assert result["status"] == "NO_DATA"
