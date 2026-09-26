from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from bemobi_distribution_sync import (  # noqa: E402
    sync_confirmed_bemobi_distribution_cash,
)


class CountingRepository:
    def __init__(self, action_count: int) -> None:
        self.read_calls = 0
        self.write_calls = 0
        self.actions = [
            {
                "id": action_id,
                "external_action_id": f"dividend-{action_id}",
                "action_type": "DIVIDEND",
                "ex_date": "2026-01-01",
                "payment_date": "2026-06-30",
                "amount_per_share": "1",
                "net_amount_per_share": None,
                "withholding_rate": None,
                "tax_treatment": None,
                "source_document_id": 1,
                "holding_id": 1,
                "holding_shares": 10,
                "holding_effective_from": "2025-01-01",
                "holding_effective_to": None,
                "fx_id": 1,
                "fx_rate_date": "2026-06-30",
                "fx_rate": "2",
                "fx_source_document_id": 1,
                "fx_source_code": "NORGES_BANK",
            }
            for action_id in range(1, action_count + 1)
        ]

    async def all(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, Any]]:
        self.read_calls += 1
        assert "LEFT JOIN bemobi_holdings" in sql
        assert "LEFT JOIN fx_rates" in sql
        return self.actions

    async def first(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> dict[str, Any] | None:
        self.read_calls += 1
        return None

    async def run(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        self.write_calls += 1


def test_distribution_reference_data_does_not_cause_n_plus_one_reads() -> None:
    repository = CountingRepository(action_count=100)

    result = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(
            repository,
            target_date="2026-06-30",
        )
    )

    assert result["actions_processed"] == 100
    assert repository.read_calls == 101
    assert repository.write_calls == 100
