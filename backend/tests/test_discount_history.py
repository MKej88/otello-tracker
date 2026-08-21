from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.discount_history import _apply_buyback_share_adjustments as reference_buyback_adjustments
from app.discount_history import _discount_statistics as reference_statistics
from app.discount_history import discount_history as reference_discount_history
from app.history import seed_curated_history
from app.nav.daily_nav import CALCULATION_VERSION

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.discount_history import _apply_buyback_share_adjustments as worker_buyback_adjustments  # noqa: E402
from src.discount_history import _discount_statistics as worker_statistics  # noqa: E402
from src.discount_history import discount_history as worker_discount_history  # noqa: E402


class SQLiteAsyncRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    async def all(self, sql: str, parameters=()):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        finally:
            connection.close()

    async def first(self, sql: str, parameters=()):
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None


def _insert_snapshot(connection, *, observed_at: str, discount: str) -> None:
    day = observed_at[:10]
    nav = 25.0
    otec = nav * (1 - float(discount) / 100)
    components = json.dumps(
        {
            "bmob3": {"price_brl": "22", "brl_nok": "1.9"},
            "otec": {"price_nok": str(otec)},
            "cash": {"cash_nok": "150000000"},
        }
    )
    connection.execute(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, '1500000000', ?, ?, ?, '1300000000', '150000000',
                  '50000000', 60000000, ?, ?, 'ESTIMATED', 'CORE', ?, 'discount history test')
        """,
        (
            observed_at,
            str(nav),
            str(otec),
            discount,
            CALCULATION_VERSION,
            f"discount-history-{observed_at}",
            components,
        ),
    )


def test_discount_statistics_use_linear_percentiles_and_midrank() -> None:
    rows = [
        {"date": "2026-08-10", "discount_pct": "-5"},
        {"date": "2026-08-11", "discount_pct": "0"},
        {"date": "2026-08-12", "discount_pct": "10"},
        {"date": "2026-08-13", "discount_pct": "20"},
        {"date": "2026-08-14", "discount_pct": "40"},
    ]
    expected = reference_statistics(rows)
    assert worker_statistics(rows) == expected
    assert expected["count"] == 5
    assert expected["p10_discount_pct"] == -3.0
    assert expected["p25_discount_pct"] == 0.0
    assert expected["median_discount_pct"] == 10.0
    assert expected["p75_discount_pct"] == 20.0
    assert expected["p90_discount_pct"] == 32.0
    assert expected["current_percentile"] == 90.0
    assert expected["premium_observation_count"] == 1
    assert expected["minimum_discount_date"] == "2026-08-10"
    assert expected["maximum_discount_date"] == "2026-08-14"


def test_buyback_adjustment_uses_exact_newsweb_trade_dates_and_matches_worker() -> None:
    rows = [
        {
            "date": day,
            "nav_total_nok": "9000",
            "nav_per_share_nok": "10",
            "otec_price_nok": "8",
            "discount_pct": "20",
            "shares_outstanding": 900 if day != "2026-08-14" else 840,
        }
        for day in ("2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14")
    ]
    periods = [
        {
            "id": 7,
            "period_start": "2026-08-11",
            "period_end": "2026-08-14",
            "weekly_shares": 60,
            "treasury_shares_after": 160,
        }
    ]
    transactions = [
        {"id": 1, "weekly_buyback_id": 7, "trade_date": "2026-08-11", "shares": 10, "quality": "CONFIRMED"},
        {"id": 2, "weekly_buyback_id": 7, "trade_date": "2026-08-12", "shares": 20, "quality": "RECONCILED"},
        {"id": 3, "weekly_buyback_id": 7, "trade_date": "2026-08-14", "shares": 30, "quality": "CONFIRMED"},
    ]
    share_counts = [
        {"id": 1, "effective_from": "2026-08-10", "total_shares": 1000, "treasury_shares": 100, "outstanding_shares": 900},
        {"id": 2, "effective_from": "2026-08-14", "total_shares": 1000, "treasury_shares": 160, "outstanding_shares": 840},
    ]

    expected = reference_buyback_adjustments(rows, periods, transactions, share_counts)
    actual = worker_buyback_adjustments(rows, periods, transactions, share_counts)

    assert actual == expected
    assert [row["shares_outstanding"] for row in expected] == [890, 870, 870, 840]
    assert [row["buyback_adjusted_shares"] for row in expected] == [10, 30, 30, 0]
    assert all(row["share_count_quality"] == "NEWSWEB_DAILY_RECONCILED" for row in expected)
    assert expected[0]["nav_per_share_nok"] == Decimal("9000") / Decimal(890)
    assert expected[0]["discount_pct"] > Decimal("20")


def test_buyback_adjustment_fails_closed_when_weekly_reconciliation_is_not_exact() -> None:
    rows = [
        {
            "date": "2026-08-11",
            "nav_total_nok": "9000",
            "nav_per_share_nok": "10",
            "otec_price_nok": "8",
            "discount_pct": "20",
            "shares_outstanding": 900,
        }
    ]
    periods = [
        {
            "id": 7,
            "period_start": "2026-08-11",
            "period_end": "2026-08-14",
            "weekly_shares": 60,
            "treasury_shares_after": 160,
        }
    ]
    transactions = [
        {"id": 1, "weekly_buyback_id": 7, "trade_date": "2026-08-11", "shares": 10, "quality": "CONFIRMED"},
        {"id": 2, "weekly_buyback_id": 7, "trade_date": "2026-08-12", "shares": 20, "quality": "REQUIRES_REVIEW"},
        {"id": 3, "weekly_buyback_id": 7, "trade_date": "2026-08-14", "shares": 30, "quality": "CONFIRMED"},
    ]
    share_counts = [
        {"id": 1, "effective_from": "2026-08-10", "total_shares": 1000, "treasury_shares": 100, "outstanding_shares": 900},
        {"id": 2, "effective_from": "2026-08-14", "total_shares": 1000, "treasury_shares": 160, "outstanding_shares": 840},
    ]

    adjusted = reference_buyback_adjustments(rows, periods, transactions, share_counts)
    assert adjusted[0]["shares_outstanding"] == 900
    assert adjusted[0]["discount_pct"] == "20"
    assert adjusted[0]["share_count_quality"] == "STORED_SNAPSHOT"


def test_discount_history_uses_only_latest_complete_snapshot_per_date(tmp_path: Path) -> None:
    database = str(tmp_path / "discount-history.db")
    init_database(database)
    seed_curated_history(database)
    with get_connection(database) as connection:
        _insert_snapshot(connection, observed_at="2026-08-13T12:00:00Z", discount="10")
        _insert_snapshot(connection, observed_at="2026-08-13T23:00:00Z", discount="20")
        _insert_snapshot(connection, observed_at="2026-08-14T23:00:00Z", discount="30")
        connection.commit()

    expected = reference_discount_history(database, days=30, max_points=50)
    actual = asyncio.run(
        worker_discount_history(SQLiteAsyncRepository(database), days=30, max_points=50)
    )

    assert actual == expected
    assert expected["ready"] is True
    assert expected["raw_count"] == 2
    assert expected["source_snapshot_count"] == 3
    assert expected["basis"]["observation_policy"] == "LATEST_COMPLETE_SNAPSHOT_PER_DATE"
    assert expected["basis"]["share_count_policy"] == "NEWSWEB_DAILY_RECONCILED_WHEN_EXACT"
    assert [point["discount_pct"] for point in expected["points"]] == [20.0, 30.0]
    assert expected["statistics"]["median_discount_pct"] == 25.0
    assert expected["statistics"]["current_percentile"] == 75.0
    assert expected["current_validated"]["discount_pct"] == 30.0
