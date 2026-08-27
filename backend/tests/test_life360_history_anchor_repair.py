from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import life360_market_data  # noqa: E402


class Repository:
    def __init__(self, *, latest: str, history_anchor: str | None) -> None:
        self.latest = latest
        self.history_anchor = history_anchor

    async def first(self, sql: str, parameters=()):
        if "mp.trading_date <= ?" in sql:
            if self.history_anchor is None:
                return None
            return {
                "trading_date": self.history_anchor,
                "observed_at": f"{self.history_anchor}T20:00:00Z",
                "price": 42.50,
                "currency": "USD",
                "source_code": "YAHOO_FINANCE",
            }
        if "ORDER BY mp.trading_date DESC, mp.observed_at DESC" in sql:
            return {
                "trading_date": self.latest,
                "observed_at": f"{self.latest}T20:00:00Z",
                "price": 43.42,
                "currency": "USD",
                "source_code": "YAHOO_FINANCE",
            }
        raise AssertionError(sql)


def test_fresh_current_lif_but_missing_1m_anchor_triggers_repair(monkeypatch) -> None:
    repository = Repository(latest="2026-08-26", history_anchor=None)
    calls = 0

    async def fake_refresh(repository_arg, *, target_date, archive_bucket, fetcher):
        nonlocal calls
        assert repository_arg is repository
        assert target_date == "2026-08-27"
        calls += 1
        repository.history_anchor = "2026-07-27"
        return {"status": "ok", "rows_written": 22}

    monkeypatch.setattr(
        life360_market_data,
        "_refresh_lif_with_independent_fallback",
        fake_refresh,
    )

    result = asyncio.run(
        life360_market_data.repair_life360_lif_if_stale(
            repository,
            target_date="2026-08-27",
        )
    )

    assert calls == 1
    assert result["status"] == "ok"
    assert result["repaired"] is True
    assert result["history_anchor_date"] == "2026-07-27"
    assert result["history_anchor_price_date"] == "2026-07-27"
    assert result["rows_written"] == 22


def test_fresh_current_lif_and_valid_1m_anchor_skip_network(monkeypatch) -> None:
    repository = Repository(latest="2026-08-26", history_anchor="2026-07-27")

    async def forbidden_refresh(*args, **kwargs):
        raise AssertionError("network refresh must be skipped when current and 1M anchor are valid")

    monkeypatch.setattr(
        life360_market_data,
        "_refresh_lif_with_independent_fallback",
        forbidden_refresh,
    )

    result = asyncio.run(
        life360_market_data.repair_life360_lif_if_stale(
            repository,
            target_date="2026-08-27",
        )
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "lif_price_fresh"
    assert result["network_fetches_avoided"] is True
    assert result["history_anchor_date"] == "2026-07-27"
    assert result["history_anchor_price_date"] == "2026-07-27"


def test_missing_1m_anchor_after_refresh_is_reported_partial(monkeypatch) -> None:
    repository = Repository(latest="2026-08-26", history_anchor=None)

    async def fake_refresh(repository_arg, *, target_date, archive_bucket, fetcher):
        assert repository_arg is repository
        return {"status": "ok", "rows_written": 1}

    monkeypatch.setattr(
        life360_market_data,
        "_refresh_lif_with_independent_fallback",
        fake_refresh,
    )

    result = asyncio.run(
        life360_market_data.repair_life360_lif_if_stale(
            repository,
            target_date="2026-08-27",
        )
    )

    assert result["status"] == "partial"
    assert result["reason"] == "lif_1m_anchor_still_missing"
    assert result["repaired"] is False
