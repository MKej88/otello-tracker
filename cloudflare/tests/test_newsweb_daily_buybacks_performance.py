from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.newsweb_daily_buybacks import (
    DailyBuybackTransaction,
    MESSAGE_FETCH_CONCURRENCY,
    _fetch_discovered_messages,
    _ingest_message,
    _store_daily_rows,
)
from src.newsweb_client import NewsWebMessage


def test_buyback_message_without_attachment_is_not_reported_as_success() -> None:
    message = NewsWebMessage(
        message_id=123,
        news_id=None,
        title="Buyback",
        body=(
            "The stock exchange notice from 1 August 2026 announcing the "
            "initiation of the share buyback program. From 1 August 2026 through "
            "7 August 2026, Otello has bought 100 shares at an average price of "
            "NOK 20.00 and a total value of NOK 2,000. The maximum number of "
            "shares that can be purchased under this buyback program is 1,000. "
            "At present date, Otello owns 350 treasury shares."
        ),
        issuer_id=1,
        issuer_sign="OTEC",
        issuer_name="Otello",
        published_at="2026-08-07T12:00:00Z",
        markets=(),
        category_ids=(),
        attachments=(),
        corrected_by_message_id=0,
        correction_for_message_id=0,
        client_announcement_id=None,
    )

    with patch(
        "src.newsweb_daily_buybacks._weekly_buyback_row",
        new=AsyncMock(return_value={"id": 42}),
    ):
        with pytest.raises(ValueError, match="mangler transaksjonsvedlegg"):
            asyncio.run(_ingest_message(object(), object(), message, fetcher=None))


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
        results = asyncio.run(_fetch_discovered_messages(discovered, fetcher=object()))

    assert maximum_active == MESSAGE_FETCH_CONCURRENCY
    assert results[0:2] == [1, 2]
    assert isinstance(results[2], RuntimeError)
    assert results[3:] == list(range(4, MESSAGE_FETCH_CONCURRENCY * 2 + 2))


def test_daily_rows_are_loaded_and_written_in_one_batch() -> None:
    class CountingRepository:
        def __init__(self) -> None:
            self.read_queries = 0
            self.batch_calls = 0
            self.batched_writes = 0

        async def all(
            self, sql: str, parameters: tuple[object, ...]
        ) -> list[dict[str, object]]:
            self.read_queries += 1
            assert parameters == (42,)
            return []

        async def run_batch(
            self,
            statements: list[tuple[str, tuple[object, ...]]],
        ) -> None:
            self.batch_calls += 1
            self.batched_writes += len(statements)

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
    assert repository.batch_calls == 1
    assert repository.batched_writes == 5
