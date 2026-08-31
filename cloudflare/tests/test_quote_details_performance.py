from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.quote_details import market_quote_details


def test_market_quotes_are_loaded_concurrently_without_changing_order() -> None:
    active = 0
    maximum_active = 0

    async def fake_quote(repository: object, symbol: str) -> dict[str, object]:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return {"ready": True, "symbol": symbol}

    with patch("src.quote_details._quote", side_effect=fake_quote):
        result = asyncio.run(market_quote_details(object()))

    assert maximum_active == 3
    assert list(result["symbols"]) == ["OTEC", "BMOB3", "LIF"]
    assert [quote["symbol"] for quote in result["symbols"].values()] == [
        "OTEC",
        "BMOB3",
        "LIF",
    ]


def test_market_quote_error_is_still_propagated() -> None:
    async def failing_quote(repository: object, symbol: str) -> dict[str, object]:
        if symbol == "BMOB3":
            raise RuntimeError("simulert databasefeil")
        return {"ready": True, "symbol": symbol}

    with patch("src.quote_details._quote", side_effect=failing_quote):
        with pytest.raises(RuntimeError, match="simulert databasefeil"):
            asyncio.run(market_quote_details(object()))
