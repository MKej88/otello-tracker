from __future__ import annotations

import asyncio
from decimal import Decimal

from src.nav_refresh import _receivable_actions


class _Repository:
    def __init__(self, action_count: int) -> None:
        self.action_count = action_count
        self.reads = 0

    async def all(self, sql: str, parameters=()) -> list[dict[str, object]]:
        self.reads += 1
        if "FROM corporate_actions ca" in sql:
            return [
                {
                    "id": action_id,
                    "action_type": "DIVIDEND",
                    "ex_date": "2025-04-30",
                    "payment_date": "2025-05-15",
                    "amount_per_share": "0.25",
                    "currency": "BRL",
                    "source_document_id": 1,
                    "component_group": "2025-Q2",
                    "holding_id": 7,
                    "holding_shares": 100,
                    "holding_ownership_pct": "1.0",
                    "holding_effective_from": "2025-01-01",
                    "holding_effective_to": None,
                    "calibration_anchor_id": 9,
                    "calibration_anchor_date": "2025-05-10",
                    "associated_receivable_reported": "5",
                }
                for action_id in range(self.action_count)
            ]
        if "FROM fx_rates" in sql:
            rate = "10" if parameters[0] == "USD" else "2"
            return [{"rate": rate, "rate_date": "2025-05-10"}]
        raise AssertionError(f"Uventet SQL: {sql}")

    async def first(self, sql: str, parameters=()) -> dict[str, object] | None:
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None


def test_receivable_actions_batch_holding_and_anchor_reads() -> None:
    repository = _Repository(action_count=40)

    result = asyncio.run(_receivable_actions(repository))

    assert len(result) == 40
    assert repository.reads == 3
    assert result[0]["holding_id"] == 7
    assert result[0]["holding_shares"] == 100
    assert result[0]["gross_brl"] == 25
    assert result[0]["calibration_factor"] == Decimal("0.025")
    assert result[0]["quality"] == "REPORTED_CALIBRATED"
