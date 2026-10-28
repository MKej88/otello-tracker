"""Regression checks for nightly preflight when fast-refresh wrote tomorrow's NAV."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import date

from src.d1_preflight import _derived_layer_dates_as_of, _fresh_enough


class DerivedLayerRepository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE cash_daily_estimates(estimate_date TEXT);
            CREATE TABLE other_net_assets_daily_estimates(estimate_date TEXT);
            CREATE TABLE nav_snapshots(
                as_of_at TEXT, nav_scope TEXT, calculation_version TEXT
            );
            """
        )

    def add_layers(self, day: str) -> None:
        self.connection.execute("INSERT INTO cash_daily_estimates VALUES (?)", (day,))
        self.connection.execute(
            "INSERT INTO other_net_assets_daily_estimates VALUES (?)", (day,)
        )
        self.connection.execute(
            "INSERT INTO nav_snapshots VALUES (?,?,?)",
            (day + "T23:59:59Z", "CORE", "core-market-nav-daily-v1"),
        )
        self.connection.execute(
            "INSERT INTO nav_snapshots VALUES (?,?,?)",
            (day + "T23:59:59Z", "FULL", "full-market-nav-daily-v2"),
        )

    async def first(self, sql: str, params: tuple[str, ...] = ()) -> dict:
        row = self.connection.execute(sql, params).fetchone()
        return dict(row) if row else {}


LAYER_FIELDS = ("cash_to", "ona_to", "core_to", "full_to")


def test_nightly_ignores_four_future_layers_and_keeps_target_coverage() -> None:
    repository = DerivedLayerRepository()
    repository.add_layers("2026-10-27")
    repository.add_layers("2026-10-28")
    result = asyncio.run(_derived_layer_dates_as_of(repository, "2026-10-27"))
    assert all(result[field] == "2026-10-27" for field in LAYER_FIELDS)
    assert all(
        _fresh_enough(result[field], date(2026, 10, 27)) for field in LAYER_FIELDS
    )


def test_nightly_uses_last_valid_day_before_target_not_future_day() -> None:
    repository = DerivedLayerRepository()
    repository.add_layers("2026-10-26")
    repository.add_layers("2026-10-28")
    result = asyncio.run(_derived_layer_dates_as_of(repository, "2026-10-27"))
    assert all(result[field] == "2026-10-26" for field in LAYER_FIELDS)
    assert all(
        _fresh_enough(result[field], date(2026, 10, 27)) for field in LAYER_FIELDS
    )


def test_future_only_layers_do_not_disguise_missing_history() -> None:
    repository = DerivedLayerRepository()
    repository.add_layers("2026-10-28")
    result = asyncio.run(_derived_layer_dates_as_of(repository, "2026-10-27"))
    assert all(result[field] is None for field in LAYER_FIELDS)
    assert not any(
        _fresh_enough(result[field], date(2026, 10, 27)) for field in LAYER_FIELDS
    )


def test_stale_layers_still_fail_even_if_new_future_layers_exist() -> None:
    repository = DerivedLayerRepository()
    repository.add_layers("2026-10-19")
    repository.add_layers("2026-10-28")
    result = asyncio.run(_derived_layer_dates_as_of(repository, "2026-10-27"))
    assert all(result[field] == "2026-10-19" for field in LAYER_FIELDS)
    assert not any(
        _fresh_enough(result[field], date(2026, 10, 27)) for field in LAYER_FIELDS
    )
