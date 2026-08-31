from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from src.newsweb_daily_buybacks import (
    BuybackTrade,
    DailyBuybackTransaction,
    MESSAGE_FETCH_CONCURRENCY,
    _fetch_discovered_messages,
    _parse_trade_line,
    _parse_undated_duplicate_time_line,
    _store_daily_rows,
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


def test_existing_daily_rows_are_loaded_in_one_query() -> None:
    class CountingRepository:
        def __init__(self) -> None:
            self.read_queries = 0
            self.write_queries = 0

        async def all(
            self, sql: str, parameters: tuple[object, ...]
        ) -> list[dict[str, object]]:
            self.read_queries += 1
            assert parameters == (42,)
            return []

        async def run(self, sql: str, parameters: tuple[object, ...]) -> None:
            self.write_queries += 1

    repository = CountingRepository()
    daily = [
        DailyBuybackTransaction(
            trade_date=f"2026-08-{day:02d}",
            shares=100,
            avg_price_nok=Decimal("10"),
            amount_nok=Decimal("1000"),
            trade_count=1,
        )
        for day in range(24, 29)
    ]

    written = asyncio.run(
        _store_daily_rows(
            repository,
            weekly_buyback_id=42,
            attachment_document_id=7,
            message=SimpleNamespace(message_id=10),
            attachment=SimpleNamespace(attachment_id=11, name="handler.pdf"),
            daily=daily,
            validation={"quality": "CONFIRMED"},
            r2_key="newsweb/handler.pdf",
        )
    )

    assert written == 5
    assert repository.read_queries == 1
    assert repository.write_queries == 5


def test_dated_trade_line_keeps_parsed_values() -> None:
    parsed = _parse_trade_line("B OTEC 1 000 10,50 10 500,00 28.08.2026 12:34:56")

    assert parsed == BuybackTrade(
        trade_date="2026-08-28",
        trade_time="12:34:56",
        shares=1_000,
        price_nok=Decimal("10.50"),
        amount_nok=Decimal("10500.00"),
    )


def test_undated_duplicate_time_line_keeps_parsed_values() -> None:
    parsed = _parse_undated_duplicate_time_line(
        "B OTEC 1 000 10,50 10 500,00 12:34:56 12:34:56"
    )

    assert parsed == BuybackTrade(
        trade_date="",
        trade_time="12:34:56",
        shares=1_000,
        price_nok=Decimal("10.50"),
        amount_nok=Decimal("10500.00"),
    )
