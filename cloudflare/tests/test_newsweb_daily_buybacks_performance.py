from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.newsweb_daily_buybacks import (
    MESSAGE_FETCH_CONCURRENCY,
    _fetch_discovered_messages,
    sync_daily_buyback_cash,
)


def test_message_details_are_fetched_concurrently_with_a_limit() -> None:
    active = 0
    maximum_active = 0

    async def fake_fetch_message(message_id: int, *, fetcher: object) -> object:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        if message_id == 3:
            raise RuntimeError("simulert API-feil")
        return message_id

    discovered = [
        SimpleNamespace(message_id=message_id)
        for message_id in range(1, MESSAGE_FETCH_CONCURRENCY * 2 + 2)
    ]
    with patch(
        "src.newsweb_daily_buybacks.fetch_message",
        side_effect=fake_fetch_message,
    ):
        results = asyncio.run(
            _fetch_discovered_messages(discovered, fetcher=object())
        )

    assert maximum_active == MESSAGE_FETCH_CONCURRENCY
    assert results[0:2] == [1, 2]
    assert isinstance(results[2], RuntimeError)
    assert results[3:] == list(range(4, MESSAGE_FETCH_CONCURRENCY * 2 + 2))


class FailingCashRepository:
    def __init__(self) -> None:
        self.deleted_ids: list[int] = []

    async def first(
        self, query: str, parameters: tuple[object, ...]
    ) -> dict[str, object] | None:
        if "FROM buybacks" in query:
            return {
                "buyback_id": 7,
                "period_end": "2026-08-28",
                "weekly_shares": 10,
            }
        return None

    async def all(
        self, query: str, parameters: tuple[object, ...]
    ) -> list[dict[str, object]]:
        if "FROM buyback_daily_transactions" in query:
            return [
                {
                    "trade_date": "2026-08-28",
                    "shares": 10,
                    "amount_nok": "100.00",
                    "source_document_id": 99,
                    "quality": "RECONCILED",
                }
            ]
        if "movement_type='OTELLO_BUYBACK'" in query:
            return [{"id": 42}]
        if "movement_type='OTELLO_BUYBACK_DAILY'" in query:
            return []
        return []

    async def run(self, query: str, parameters: tuple[object, ...]) -> None:
        if query.startswith("DELETE FROM cash_movements"):
            self.deleted_ids.append(int(parameters[0]))
            return
        if "INSERT INTO cash_movements" in query:
            raise RuntimeError("simulert D1-feil")


def test_weekly_cash_survives_failure_while_daily_rows_are_written() -> None:
    repository = FailingCashRepository()

    with pytest.raises(RuntimeError, match="simulert D1-feil"):
        asyncio.run(sync_daily_buyback_cash(repository, weekly_buyback_id=7))

    assert repository.deleted_ids == []
