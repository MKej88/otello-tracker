from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import quote_details as worker_quotes  # noqa: E402


def test_independent_quote_reads_start_concurrently(monkeypatch) -> None:
    started: set[str] = set()
    all_started = asyncio.Event()

    async def latest_price(_repository, _symbol):
        return {
            "trading_date": "2026-09-25",
            "price": 10,
            "price_type": "CLOSE",
            "source_code": "B3",
        }

    async def independent_read(name: str, result):
        started.add(name)
        if len(started) == 3:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=0.5)
        return result

    async def daily_history(_repository, _symbol, _trading_date):
        return await independent_read("history", [])

    async def latest_close(_repository, _symbol, _before_date=None):
        return await independent_read("close", None)

    async def day_stats(_repository, _symbol, _trading_date):
        return await independent_read(
            "session", {"open": None, "low": None, "high": None, "basis": "MISSING"}
        )

    async def volume_stats(_repository, _symbol, history, _latest):
        assert history == []
        assert started == {"history", "close", "session"}
        return {"latest": None, "average_3m": None, "average_sessions": 0}

    monkeypatch.setattr(worker_quotes, "_latest_price", latest_price)
    monkeypatch.setattr(worker_quotes, "_daily_history", daily_history)
    monkeypatch.setattr(worker_quotes, "_latest_close", latest_close)
    monkeypatch.setattr(worker_quotes, "_day_stats", day_stats)
    monkeypatch.setattr(worker_quotes, "_volume_stats", volume_stats)

    result = asyncio.run(worker_quotes._quote(object(), "BMOB3"))

    assert result["ready"] is True
    assert result["session"]["basis"] == "MISSING"


def test_concurrent_quote_read_keeps_database_error_visible(monkeypatch) -> None:
    async def latest_price(_repository, _symbol):
        return {
            "trading_date": "2026-09-25",
            "price": 10,
            "price_type": "CLOSE",
            "source_code": "B3",
        }

    async def failed_history(_repository, _symbol, _trading_date):
        raise RuntimeError("D1 read failed")

    async def latest_close(_repository, _symbol, _before_date=None):
        return None

    async def day_stats(_repository, _symbol, _trading_date):
        return {}

    monkeypatch.setattr(worker_quotes, "_latest_price", latest_price)
    monkeypatch.setattr(worker_quotes, "_daily_history", failed_history)
    monkeypatch.setattr(worker_quotes, "_latest_close", latest_close)
    monkeypatch.setattr(worker_quotes, "_day_stats", day_stats)

    with pytest.raises(RuntimeError, match="D1 read failed"):
        asyncio.run(worker_quotes._quote(object(), "BMOB3"))
