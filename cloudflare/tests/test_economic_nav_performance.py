from __future__ import annotations

import asyncio
import json

from src.economic_nav import _cash_fx_revaluation


class ConcurrentFxRepository:
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.all_started = asyncio.Event()

    async def all(self, _sql: str, _parameters=()) -> list[dict[str, object]]:
        return [
            {
                "id": 1,
                "metadata_json": json.dumps(
                    {
                        "as_of_date": "2026-01-01",
                        "exposures": [
                            {"currency": "USD", "usd_equivalent": "10"}
                        ],
                    }
                ),
            }
        ]

    async def first(
        self, _sql: str, parameters=()
    ) -> dict[str, str] | None:
        base, day, _floor = parameters
        self.started.append((base, day))
        if len(self.started) == 4:
            self.all_started.set()
        await asyncio.wait_for(self.all_started.wait(), timeout=0.5)
        return {"rate": "10", "rate_date": day}


def test_cash_fx_rates_are_loaded_concurrently() -> None:
    repository = ConcurrentFxRepository()

    result = asyncio.run(
        _cash_fx_revaluation(
            repository,
            cash_anchor_date="2026-01-01",
            as_of_date="2026-09-12",
        )
    )

    assert result["ready"] is True
    assert result["adjustment_nok"] == 0
    assert repository.started == [
        ("USD", "2026-01-01"),
        ("BRL", "2026-01-01"),
        ("USD", "2026-09-12"),
        ("BRL", "2026-09-12"),
    ]
