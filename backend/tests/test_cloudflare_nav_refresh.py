from __future__ import annotations

import asyncio
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.nav.daily_nav import calculate_daily_core_nav
from app.nav.full_nav import FULL_CALCULATION_VERSION, rebuild_daily_full_nav
from app.nav.option_liability import option_liability_for_day as reference_option_liability
from app.nav.other_net_assets import rebuild_other_net_assets_anchors

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.nav_refresh import (  # noqa: E402
    CORE_CALCULATION_VERSION,
    refresh_dirty_nav_layers,
)
from src.option_liability import option_liability_for_day as worker_option_liability  # noqa: E402


class SQLiteAsyncWriteRepository:
    """Run D1 Worker model code against SQLite's D1-compatible SQL semantics."""

    def __init__(self, database_path: str):
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    async def all(self, sql: str, parameters=()):
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        finally:
            connection.close()

    async def first(self, sql: str, parameters=()):
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None

    async def run(self, sql: str, parameters=()):
        connection = self._connect()
        try:
            cursor = connection.execute(sql, parameters)
            connection.commit()
            return {"changes": cursor.rowcount, "last_row_id": cursor.lastrowid}
        finally:
            connection.close()


def _source_id(connection, code: str) -> int:
    return int(connection.execute("SELECT id FROM sources WHERE code=?", (code,)).fetchone()["id"])


def _instrument_id(connection, symbol: str) -> int:
    return int(connection.execute("SELECT id FROM instruments WHERE symbol=?", (symbol,)).fetchone()["id"])


def _insert_fx(connection, day: str, base: str, rate: str) -> None:
    connection.execute(
        """
        INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
        VALUES (?, 'NOK', ?, ?, ?)
        """,
        (base, f"{day}T16:00:00Z", rate, _source_id(connection, "ECB")),
    )


def _insert_price(
    connection,
    day: str,
    symbol: str,
    price: str,
    source: str,
    *,
    price_type: str = "CLOSE",
    observed_at: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO market_prices(
            instrument_id, observed_at, trading_date, price_type, price, currency,
            source_id, quality, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DIRECT', '{}')
        """,
        (
            _instrument_id(connection, symbol),
            observed_at or f"{day}T16:30:00Z",
            day,
            price_type,
            price,
            "NOK" if symbol == "OTEC" else "BRL",
            _source_id(connection, source),
        ),
    )


def _database(tmp_path: Path) -> tuple[str, str]:
    target = "2026-08-17"
    database = str(tmp_path / "cloudflare-dirty-nav.db")
    init_database(database)
    seed_curated_history(database)
    with get_connection(database) as connection:
        ona_anchor_dates = {
            str(row["as_of_date"])
            for row in connection.execute(
                "SELECT as_of_date FROM other_net_assets_reported_anchors"
            ).fetchall()
        }
        # The normalized ONA layer deliberately depends on USD/NOK for every report
        # anchor. Seed a deterministic rate at each anchor so this fixture represents
        # the same bootstrap state that production D1 receives before fast refresh.
        for anchor_day in sorted(ona_anchor_dates | {target}):
            _insert_fx(connection, anchor_day, "USD", "10")
        _insert_fx(connection, target, "BRL", "2")
        _insert_price(connection, target, "OTEC", "18", "EURONEXT")
        _insert_price(connection, target, "BMOB3", "20", "B3")
        connection.commit()

    normalized = rebuild_other_net_assets_anchors(database)
    assert normalized["written"] > 0
    assert normalized["skipped"] == []
    return database, target


def test_worker_option_liability_matches_reference(tmp_path: Path) -> None:
    database, target = _database(tmp_path)
    with get_connection(database) as connection:
        expected = reference_option_liability(connection, target)
    actual = asyncio.run(worker_option_liability(SQLiteAsyncWriteRepository(database), target))
    assert actual is not None and expected is not None
    for key in (
        "liability_nok",
        "liability_usd",
        "fair_value_per_option_nok",
        "recognition_fraction",
        "spot_nok",
        "strike_nok",
        "quality",
        "inputs",
    ):
        assert actual[key] == expected[key]


def test_dirty_nav_builds_core_and_option_aware_full_idempotently(tmp_path: Path) -> None:
    database, target = _database(tmp_path)
    repository = SQLiteAsyncWriteRepository(database)

    first = asyncio.run(refresh_dirty_nav_layers(repository, target_date=target))
    assert first["status"] == "ok"
    assert first["nav_date"] == target
    assert first["live_calendar_snapshot"] is True
    assert set(first["dirty_layers"]) == {
        "daily_cash",
        "daily_other_net_assets",
        "daily_core_nav",
        "daily_full_nav",
    }

    with get_connection(database) as connection:
        core = connection.execute(
            """
            SELECT nav_total_nok, nav_per_share_nok, inputs_hash
            FROM nav_snapshots
            WHERE as_of_at=? AND calculation_version=? AND nav_scope='CORE'
            """,
            (f"{target}T23:59:59Z", CORE_CALCULATION_VERSION),
        ).fetchone()
        expected_core = calculate_daily_core_nav(connection, target)
        full = connection.execute(
            """
            SELECT nav_total_nok, nav_per_share_nok, other_net_assets_nok,
                   inputs_hash, components_json
            FROM nav_snapshots
            WHERE as_of_at=? AND calculation_version=? AND nav_scope='FULL'
            """,
            (f"{target}T23:59:59Z", FULL_CALCULATION_VERSION),
        ).fetchone()
        ona = connection.execute(
            """
            SELECT amount_nok, option_liability_nok, option_quality
            FROM other_net_assets_daily_estimates WHERE estimate_date=?
            """,
            (target,),
        ).fetchone()

    assert core is not None and full is not None and ona is not None
    assert Decimal(core["nav_total_nok"]) == expected_core["nav_total_nok"]
    assert Decimal(core["nav_per_share_nok"]) == expected_core["nav_per_share_nok"]
    assert ona["option_quality"] == "FORECAST_MARK_TO_MARKET"
    assert Decimal(ona["option_liability_nok"]) > 0
    assert Decimal(full["nav_total_nok"]) == Decimal(core["nav_total_nok"]) + Decimal(ona["amount_nok"])

    second = asyncio.run(refresh_dirty_nav_layers(repository, target_date=target))
    assert second["status"] == "ok"
    assert second["dirty_layers"] == []
    assert all(step.get("skipped") is True for step in second["steps"].values())


def test_intraday_otec_change_marks_option_core_and_full_dirty_but_not_cash(tmp_path: Path) -> None:
    database, target = _database(tmp_path)
    repository = SQLiteAsyncWriteRepository(database)
    asyncio.run(refresh_dirty_nav_layers(repository, target_date=target))

    with get_connection(database) as connection:
        before = connection.execute(
            "SELECT option_liability_nok FROM other_net_assets_daily_estimates WHERE estimate_date=?",
            (target,),
        ).fetchone()
        _insert_price(
            connection,
            target,
            "OTEC",
            "19",
            "EURONEXT",
            price_type="LAST",
            observed_at=f"{target}T20:00:00Z",
        )
        connection.commit()

    changed = asyncio.run(refresh_dirty_nav_layers(repository, target_date=target))
    # Same-day authoritative CLOSE remains stronger than LAST, so no layer should change.
    assert changed["dirty_layers"] == []

    with get_connection(database) as connection:
        connection.execute(
            "DELETE FROM market_prices WHERE trading_date=? AND price_type='CLOSE' AND instrument_id=?",
            (target, _instrument_id(connection, "OTEC")),
        )
        connection.commit()

    changed = asyncio.run(refresh_dirty_nav_layers(repository, target_date=target))
    assert changed["steps"]["daily_cash"]["dirty"] is False
    assert changed["steps"]["daily_other_net_assets"]["dirty"] is True
    assert changed["steps"]["daily_core_nav"]["dirty"] is True
    assert changed["steps"]["daily_full_nav"]["dirty"] is True

    with get_connection(database) as connection:
        after = connection.execute(
            "SELECT option_liability_nok FROM other_net_assets_daily_estimates WHERE estimate_date=?",
            (target,),
        ).fetchone()
        worker_full = connection.execute(
            "SELECT nav_per_share_nok FROM nav_snapshots WHERE as_of_at=? AND calculation_version=?",
            (f"{target}T23:59:59Z", FULL_CALCULATION_VERSION),
        ).fetchone()
        connection.execute(
            "DELETE FROM nav_snapshots WHERE as_of_at=? AND calculation_version=?",
            (f"{target}T23:59:59Z", FULL_CALCULATION_VERSION),
        )
        connection.commit()

    assert Decimal(after["option_liability_nok"]) > Decimal(before["option_liability_nok"])
    rebuild_daily_full_nav(database, start_date=target, end_date=target)
    with get_connection(database) as connection:
        reference_full = connection.execute(
            "SELECT nav_per_share_nok FROM nav_snapshots WHERE as_of_at=? AND calculation_version=?",
            (f"{target}T23:59:59Z", FULL_CALCULATION_VERSION),
        ).fetchone()
    assert worker_full["nav_per_share_nok"] == reference_full["nav_per_share_nok"]
