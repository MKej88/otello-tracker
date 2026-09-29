from __future__ import annotations

import asyncio

from src.option_liability import option_liability_for_day


class _Repository:
    def __init__(self) -> None:
        self.reads = 0
        self.report_document_reads = 0

    async def all(self, sql: str, parameters=()) -> list[dict[str, object]]:
        self.reads += 1
        if "FROM source_documents" in sql:
            self.report_document_reads += 1
            return []
        if "FROM market_prices" in sql:
            return [
                {
                    "id": 1,
                    "trading_date": "2026-01-05",
                    "observed_at": "2026-01-05T15:30:00Z",
                    "price_type": "CLOSE",
                    "price": "25",
                    "quality": "DIRECT",
                    "source_code": "EURONEXT",
                }
            ]
        if "FROM fx_rates" in sql:
            return [{"id": 2, "rate_date": "2026-01-05", "rate": "10"}]
        if "FROM corporate_actions" in sql:
            return []
        raise AssertionError(f"Uventet SQL: {sql}")

    async def first(self, sql: str, parameters=()) -> dict[str, object] | None:
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None


def test_option_liability_reuses_report_anchors() -> None:
    repository = _Repository()

    result = asyncio.run(option_liability_for_day(repository, "2026-01-05"))

    assert result is not None
    assert result["liability_nok"] > 0
    assert repository.report_document_reads == 1
    assert repository.reads == 6
