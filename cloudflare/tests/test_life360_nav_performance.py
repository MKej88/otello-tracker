from __future__ import annotations

import asyncio

import pytest
from src.life360_nav import life360_nav_adjustment

CURRENT_DATE = "2026-08-14"
ANCHOR_DATE = "2026-06-30"


class _ConcurrentRepository:
    def __init__(self, anchor_date: str = ANCHOR_DATE) -> None:
        self.anchor_date = anchor_date
        self.started: list[tuple[str, str]] = []
        self.all_started = asyncio.Event()

    async def first(self, sql: str, parameters=()):
        if "FROM other_net_assets_reported_anchors" in sql:
            return {"as_of_date": self.anchor_date}
        if "FROM life360_holding_anchors" in sql:
            key = ("holding", parameters[0])
        elif "FROM market_prices" in sql:
            key = ("price", parameters[2])
        else:
            assert "FROM fx_rates" in sql
            key = ("fx", parameters[1])
        self.started.append(key)
        expected_reads = 3 if self.anchor_date == CURRENT_DATE else 5
        if len(self.started) == expected_reads:
            self.all_started.set()
        await asyncio.wait_for(self.all_started.wait(), timeout=0.5)
        return None


@pytest.mark.parametrize("anchor_date", [ANCHOR_DATE, CURRENT_DATE])
def test_life360_reads_overlap_without_duplicate_dates(anchor_date: str) -> None:
    repository = _ConcurrentRepository(anchor_date)

    result = asyncio.run(life360_nav_adjustment(repository, as_of_date=CURRENT_DATE))

    expected = {
        ("holding", CURRENT_DATE),
        ("holding", anchor_date),
        ("price", CURRENT_DATE),
        ("price", anchor_date),
        ("fx", CURRENT_DATE),
    }
    assert set(repository.started) == expected
    assert len(repository.started) == len(expected)
    assert result["ready"] is False
    assert result["reason"] == (
        "missing_current_life360_holding_and_anchor_life360_holding"
        "_and_current_lif_price_and_anchor_lif_price_and_usd_nok"
    )
    assert result["adjustment_nok"] == 0


def test_life360_preserves_first_error_when_later_read_fails_sooner() -> None:
    first_error = ValueError("first logical read failed")
    later_error = RuntimeError("later read failed sooner")

    class Repository:
        def __init__(self) -> None:
            self.later_failed = asyncio.Event()

        async def first(self, sql: str, parameters=()):
            if "FROM other_net_assets_reported_anchors" in sql:
                return {"as_of_date": ANCHOR_DATE}
            if "FROM life360_holding_anchors" in sql and parameters[0] == CURRENT_DATE:
                await asyncio.wait_for(self.later_failed.wait(), timeout=0.5)
                raise first_error
            self.later_failed.set()
            raise later_error

    with pytest.raises(ValueError) as captured:
        asyncio.run(life360_nav_adjustment(Repository(), as_of_date=CURRENT_DATE))

    assert captured.value is first_error


def test_life360_cancellation_cancels_pending_reads() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        pending = asyncio.Event()
        reads = 0
        cancelled = 0

        class Repository:
            async def first(self, sql: str, parameters=()):
                nonlocal reads, cancelled
                if "FROM other_net_assets_reported_anchors" in sql:
                    return {"as_of_date": ANCHOR_DATE}
                reads += 1
                if reads == 5:
                    started.set()
                try:
                    await pending.wait()
                except asyncio.CancelledError:
                    cancelled += 1
                    raise

        task = asyncio.create_task(
            life360_nav_adjustment(Repository(), as_of_date=CURRENT_DATE)
        )
        await asyncio.wait_for(started.wait(), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled == 5

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("day", "anchor", "reason", "reads"),
    [
        ("2025-06-30", None, "life360_fair_value_policy_not_active", 0),
        (CURRENT_DATE, None, "missing_life360_report_anchor", 1),
    ],
)
def test_life360_short_circuits_without_starting_dependent_reads(
    day: str, anchor: None, reason: str, reads: int
) -> None:
    class Repository:
        calls = 0

        async def first(self, sql: str, parameters=()):
            self.calls += 1
            assert "FROM other_net_assets_reported_anchors" in sql
            return anchor

    repository = Repository()
    result = asyncio.run(life360_nav_adjustment(repository, as_of_date=day))

    assert result["ready"] is False
    assert result["reason"] == reason
    assert repository.calls == reads
