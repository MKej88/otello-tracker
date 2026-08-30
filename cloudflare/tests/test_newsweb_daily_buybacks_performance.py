from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from src.newsweb_daily_buybacks import (
    MESSAGE_FETCH_CONCURRENCY,
    _fetch_discovered_messages,
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
