from __future__ import annotations

import asyncio
from decimal import Decimal

from src.nav_refresh import _documented_receivable_factor, _receivable_actions, _receivable_for_day


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


def test_net_entitlement_uses_published_terms_and_keeps_unknown_tax_actionable() -> None:
    action = {"action_type": "JCP", "amount_per_share": "0.19178292",
              "net_amount_per_share": "0.15822091", "withholding_rate": "0.175",
              "source_document_id": 88}
    factor, basis = _documented_receivable_factor(action)
    assert basis == "PUBLISHED_NET"
    assert abs(factor * Decimal(action["amount_per_share"]) - Decimal("0.15822091")) < Decimal("0.000000001")
    assert _documented_receivable_factor({**action, "net_amount_per_share": None}) == (Decimal("0.825"), "PUBLISHED_WITHHOLDING_RATE")
    assert _documented_receivable_factor({**action, "source_document_id": None}) is None
    assert _documented_receivable_factor({**action, "net_amount_per_share": None, "withholding_rate": None}) is None
    assert _documented_receivable_factor({**action, "net_amount_per_share": "0.18"}) is None
    assert _documented_receivable_factor({**action, "net_amount_per_share": "NaN"}) is None


def test_source_documented_net_receivable_from_ex_date_until_payment() -> None:
    class Repo(_Repository):
        async def all(self, sql, parameters=()):
            rows = await super().all(sql, parameters)
            if "FROM corporate_actions ca" in sql:
                for row in rows:
                    row.update(action_type="JCP", amount_per_share="0.20",
                               net_amount_per_share="0.165", withholding_rate="0.175",
                               calibration_anchor_id=None)
            return rows

    repo = Repo(1)
    actions = asyncio.run(_receivable_actions(repo))
    assert actions[0]["quality"] == "ESTIMATED_NET"
    amount, quality, components = asyncio.run(_receivable_for_day(repo, "2025-05-01", actions))
    assert amount == Decimal("33")
    assert quality == "ESTIMATED_NET"
    assert components[0]["calibration"]["basis"] == "PUBLISHED_NET"
    assert asyncio.run(_receivable_for_day(repo, "2025-05-15", actions)) == (Decimal("0"), "NONE", [])
    unknown = {**actions[0], "id": 100, "quality": "ESTIMATED_GROSS", "calibration_factor": Decimal("1")}
    _, mixed_quality, _ = asyncio.run(_receivable_for_day(repo, "2025-05-01", [actions[0], unknown]))
    assert mixed_quality == "ESTIMATED_GROSS"
