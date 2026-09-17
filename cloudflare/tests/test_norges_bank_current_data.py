from __future__ import annotations

import asyncio

import pytest

from src import norges_bank_full_refresh


class _Repository:
    def __init__(self, currencies: tuple[str, ...]) -> None:
        self.currencies = currencies
        self.target_queries: list[tuple[str, ...]] = []

    async def all(self, sql: str, parameters: tuple = ()) -> list[dict]:
        if "SELECT DISTINCT fr.base_currency" not in sql:
            raise AssertionError(f"Uventet spørring: {sql}")
        self.target_queries.append(parameters)
        return [{"base_currency": currency} for currency in self.currencies]


async def _complete_coverage(
    repository,
    *,
    target_date: str,
) -> tuple[bool, dict, str]:
    del repository
    return True, {}, norges_bank_full_refresh.norges_bank_history_start(target_date)


async def _incomplete_coverage(
    repository,
    *,
    target_date: str,
) -> tuple[bool, dict, str]:
    del repository
    return False, {}, norges_bank_full_refresh.norges_bank_history_start(target_date)


async def _no_history_rebuild(
    repository,
    *,
    required_start: str,
    target_date: str,
) -> bool:
    del repository, required_start, target_date
    return False


async def _unexpected_fetch(*args, **kwargs):
    del args, kwargs
    raise AssertionError("Norges Bank skulle ikke hentes")


async def _failing_fetch(*args, **kwargs):
    del args, kwargs
    raise RuntimeError("fetch-called")


def test_full_refresh_skips_fetch_when_required_target_fx_exists(monkeypatch) -> None:
    repository = _Repository(("BRL", "USD"))
    monkeypatch.setattr(
        norges_bank_full_refresh,
        "_norges_bank_coverage",
        _complete_coverage,
    )
    monkeypatch.setattr(
        norges_bank_full_refresh,
        "history_rebuild_needed",
        _no_history_rebuild,
    )

    result = asyncio.run(
        norges_bank_full_refresh.refresh_norges_bank_fx(
            repository,
            target_date="2026-09-16",
            fetcher=_unexpected_fetch,
        )
    )

    assert result["status"] == "ok"
    assert result["skipped"] is True
    assert result["reason"] == "required_target_fx_already_present"
    assert result["rows_written"] == 0
    assert result["history_backfill"] is False
    assert repository.target_queries == [("2026-09-16",)]


def test_full_refresh_fetches_when_required_target_fx_is_missing(monkeypatch) -> None:
    repository = _Repository(("BRL",))
    monkeypatch.setattr(
        norges_bank_full_refresh,
        "_norges_bank_coverage",
        _complete_coverage,
    )
    monkeypatch.setattr(
        norges_bank_full_refresh,
        "history_rebuild_needed",
        _no_history_rebuild,
    )

    with pytest.raises(RuntimeError, match="fetch-called"):
        asyncio.run(
            norges_bank_full_refresh.refresh_norges_bank_fx(
                repository,
                target_date="2026-09-16",
                fetcher=_failing_fetch,
            )
        )


def test_full_refresh_keeps_history_backfill_when_coverage_is_incomplete(
    monkeypatch,
) -> None:
    repository = _Repository(("BRL", "USD"))
    monkeypatch.setattr(
        norges_bank_full_refresh,
        "_norges_bank_coverage",
        _incomplete_coverage,
    )

    with pytest.raises(RuntimeError, match="fetch-called"):
        asyncio.run(
            norges_bank_full_refresh.refresh_norges_bank_fx(
                repository,
                target_date="2026-09-16",
                fetcher=_failing_fetch,
            )
        )

    assert repository.target_queries == []
