from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.quote_details import _latest_price, _quote


class _CaptureRepository:
    def __init__(self) -> None:
        self.query = ""
        self.params: tuple[object, ...] = ()

    async def first(self, query, params=()):
        self.query = query
        self.params = params
        return None


def test_otec_latest_price_sql_prioritizes_last_trade() -> None:
    repository = _CaptureRepository()
    asyncio.run(_latest_price(repository, "OTEC"))

    assert "WHEN ?='OTEC' AND mp.price_type='LAST' THEN 0" in repository.query
    assert repository.params == ("OTEC", "OTEC", "OTEC")


def test_otec_same_day_close_does_not_replace_last_trade() -> None:
    latest = {
        "id": 2,
        "trading_date": "2026-09-04",
        "observed_at": "2026-09-04T14:15:00Z",
        "price_type": "LAST",
        "price": 17.98,
        "currency": "NOK",
        "quality": "DIRECT",
        "source_code": "EURONEXT",
    }
    completed = {
        "trading_date": "2026-09-04",
        "price": 17.84,
        "source_code": "EURONEXT",
        "close_basis": "DELAYED_TRADE_SUM",
    }

    with (
        patch("src.quote_details._latest_price", new=AsyncMock(return_value=latest)),
        patch(
            "src.quote_details._latest_close",
            new=AsyncMock(return_value=completed),
        ),
        patch("src.quote_details._daily_history", new=AsyncMock(return_value=[])),
        patch(
            "src.quote_details._volume_stats",
            new=AsyncMock(
                return_value={
                    "latest": None,
                    "average_3m": None,
                    "average_sessions": 0,
                }
            ),
        ),
        patch("src.quote_details._day_stats", new=AsyncMock(return_value={})),
    ):
        quote = asyncio.run(_quote(object(), "OTEC"))

    assert quote["last"] == 17.98
    assert quote["last_price_type"] == "LAST"
    assert quote["last_updated_at"] == "2026-09-04T14:15:00Z"


def test_all_current_otec_consumers_use_shared_live_helper() -> None:
    expected = {
        "dashboard_service.py": "latest_otec_current_price(repository)",
        "economic_nav_investor.py": "latest_otec_current_price(repository)",
        "buyback_service.py": "latest_otec_current_price(repository)",
    }
    root = Path(__file__).resolve().parents[1] / "src"
    for filename, marker in expected.items():
        assert marker in (root / filename).read_text(encoding="utf-8")

    buyback_source = (root / "buyback_service.py").read_text(encoding="utf-8")
    assert "if as_of_date is None:" in buyback_source


def test_hot_snapshot_version_is_bumped_for_live_price_semantics() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "dashboard_hot_snapshot.py"
    ).read_text(encoding="utf-8")
    assert 'STATE_KEY = "dashboard_hot_snapshot_v7"' in source
    assert "SNAPSHOT_VERSION = 7" in source
