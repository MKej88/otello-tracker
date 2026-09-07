from __future__ import annotations

import asyncio

from src.fx_history_rebuild import _normalize_fx_derived_cash


class _Repository:
    def __init__(self, *, rows_per_table: int = 100) -> None:
        self.rows_per_table = rows_per_table
        self.reads = 0
        self.writes: list[tuple[str, tuple]] = []

    async def all(self, sql: str, parameters: tuple = ()) -> list[dict]:
        self.reads += 1
        if "FROM fx_rates" in sql:
            return [
                {
                    "id": 2,
                    "base_currency": "USD",
                    "rate_date": "2026-08-14",
                    "rate": "10.50",
                },
                {
                    "id": 1,
                    "base_currency": "BRL",
                    "rate_date": "2026-08-10",
                    "rate": "1.90",
                },
            ]
        if "FROM cash_anchors" in sql:
            return [
                {
                    "id": row_id,
                    "as_of_date": "2026-08-17",
                    "reported_amount": "2",
                    "reported_currency": "USD",
                }
                for row_id in range(self.rows_per_table)
            ]
        if "FROM cash_movements" in sql:
            return [
                {
                    "id": row_id,
                    "movement_date": "2026-08-17",
                    "amount_original": "3",
                    "currency": "BRL",
                }
                for row_id in range(self.rows_per_table)
            ]
        raise AssertionError(f"Uventet spørring: {sql}")

    async def run(self, sql: str, parameters: tuple = ()) -> None:
        self.writes.append((sql, parameters))


def test_cash_normalization_loads_fx_rates_once_and_preserves_lookback() -> None:
    repository = _Repository()

    result = asyncio.run(
        _normalize_fx_derived_cash(
            repository,
            start_date="2026-08-17",
            end_date="2026-08-17",
        )
    )

    assert result == {
        "cash_anchors_updated": 100,
        "cash_movements_updated": 100,
    }
    assert repository.reads == 3
    assert len(repository.writes) == 200
    assert {parameters[0] for _, parameters in repository.writes} == {
        "5.70",
        "21.00",
    }
