from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from app.buybacks.activity import seed_otec_activity_history
from app.buybacks.forecast import buyback_forecast as reference_buyback_forecast
from app.dashboard import dashboard_history as reference_dashboard_history
from app.dashboard import dashboard_summary as reference_dashboard_summary
from app.dashboard_freshness import enrich_dashboard_summary as reference_enrich_summary
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document
from app.history import seed_curated_history
from app.marketdata.oslo_calendar import oslo_bors_trading_days as reference_oslo_days
from app.nav.daily_nav import CALCULATION_VERSION as CORE_VERSION
from app.nav.full_nav import FULL_CALCULATION_VERSION as FULL_VERSION

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.buyback_service import buyback_forecast as worker_buyback_forecast  # noqa: E402
from src.dashboard_service import (  # noqa: E402
    dashboard_history as worker_dashboard_history,
    dashboard_summary as worker_dashboard_summary,
    enrich_dashboard_summary as worker_enrich_summary,
)
from src.oslo_calendar import oslo_bors_trading_days as worker_oslo_days  # noqa: E402
from src.repository import D1Repository  # noqa: E402


class SQLiteAsyncRepository:
    """Exercise Worker query code against the same SQLite SQL semantics used by D1."""

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


def _components(*, day: str, otec: str, bmob3: str, brl: str, cash: str, status: str):
    return {
        "bmob3": {
            "price_brl": bmob3,
            "brl_nok": brl,
            "price_source": "B3",
            "price_quality": "DIRECT",
            "price_date": day,
            "price_observed_at": f"{day}T20:00:00Z",
            "price_type": "CLOSE",
            "brl_nok_date": day,
        },
        "otec": {
            "price_nok": otec,
            "price_source": "EURONEXT",
            "price_quality": "DIRECT",
            "price_date": day,
            "price_observed_at": f"{day}T14:30:00Z",
            "price_type": "CLOSE",
            "share_count_quality": "REPORTED",
        },
        "cash": {
            "cash_nok": cash,
            "quality": "FORECAST_PARTIAL" if status == "DEGRADED" else "ANCHORED_ESTIMATE",
            "calibration_quality": "ANCHORED",
        },
    }


def _insert_nav_pair(
    connection,
    *,
    day: str,
    nav: str,
    otec: str,
    discount: str,
    cash: str,
    bmob3: str,
    brl: str,
    status: str,
):
    components = json.dumps(
        _components(day=day, otec=otec, bmob3=bmob3, brl=brl, cash=cash, status=status)
    )
    common = (
        f"{day}T23:59:59Z",
        "1500000000",
        nav,
        otec,
        discount,
        "1350000000",
        cash,
        70_000_000,
        status,
    )
    connection.execute(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '0', ?, ?, ?, ?, 'CORE', ?, 'parity fixture')
        """,
        (*common[:7], common[7], CORE_VERSION, f"core-{day}", common[8], components),
    )
    full_nav = str(float(nav) + 0.15)
    connection.execute(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, '1510500000', ?, ?, ?, ?, ?, '10500000', ?, ?, ?, ?, 'FULL', '{}', 'parity fixture')
        """,
        (
            common[0],
            full_nav,
            otec,
            discount,
            common[5],
            cash,
            common[7],
            FULL_VERSION,
            f"full-{day}",
            status,
        ),
    )


def _dashboard_database(tmp_path: Path) -> str:
    database = str(tmp_path / "worker-dashboard.db")
    init_database(database)
    seed_curated_history(database)
    with get_connection(database) as connection:
        _insert_nav_pair(
            connection,
            day="2026-08-13",
            nav="23.00",
            otec="17.86",
            discount="22.34782608695652",
            cash="160000000",
            bmob3="22.88",
            brl="1.90",
            status="ESTIMATED",
        )
        _insert_nav_pair(
            connection,
            day="2026-08-14",
            nav="23.50",
            otec="17.20",
            discount="26.80851063829787",
            cash="158000000",
            bmob3="22.81",
            brl="1.91",
            status="ESTIMATED",
        )
        connection.commit()
    return database


def _seed_current_program(database: str) -> None:
    weeks = [
        ("2026-06-08", "2026-06-12", 79_600, 79_600),
        ("2026-06-15", "2026-06-19", 72_009, 151_609),
        ("2026-06-22", "2026-06-26", 52_419, 204_028),
        ("2026-06-29", "2026-07-03", 63_554, 267_582),
        ("2026-07-06", "2026-07-10", 65_300, 332_882),
        ("2026-07-13", "2026-07-17", 52_599, 385_481),
        ("2026-07-20", "2026-07-24", 50_500, 435_981),
        ("2026-07-27", "2026-07-31", 46_400, 482_381),
        ("2026-08-03", "2026-08-07", 58_500, 540_881),
        ("2026-08-10", "2026-08-14", 59_512, 600_393),
    ]
    with get_connection(database) as connection:
        document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="worker-parity-current-program",
            document_type="REGULATORY_NEWS",
            title="Worker parity current program",
            url="https://newsweb.oslobors.no/message/worker-parity",
        )
        cursor = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, max_shares,
                max_price_nok, status, source_document_id, notes
            ) VALUES ('otec-buyback-2026-06-08', '2026-06-08T00:00:00Z',
                      '2026-06-08', 2192046, '20', 'ACTIVE', ?, 'worker parity')
            """,
            (document_id,),
        )
        program_id = int(cursor.lastrowid)
        for start, end, shares, cumulative in weeks:
            connection.execute(
                """
                INSERT INTO buybacks(
                    program_id, period_start, trade_date, shares, avg_price_nok, amount_nok,
                    cumulative_program_shares, treasury_shares_after, source_document_id
                ) VALUES (?, ?, ?, ?, '17', ?, ?, ?, ?)
                """,
                (
                    program_id,
                    start,
                    end,
                    shares,
                    str(shares * 17),
                    cumulative,
                    5_000_000 + cumulative,
                    document_id,
                ),
            )
        connection.commit()


def test_worker_dashboard_summary_matches_reference_exactly(tmp_path: Path) -> None:
    database = _dashboard_database(tmp_path)
    expected = reference_enrich_summary(reference_dashboard_summary(database), database)
    repository = SQLiteAsyncRepository(database)

    async def run():
        summary = await worker_dashboard_summary(repository)
        return await worker_enrich_summary(summary, repository)

    assert asyncio.run(run()) == expected


def test_worker_dashboard_history_matches_reference_exactly(tmp_path: Path) -> None:
    database = _dashboard_database(tmp_path)
    expected = reference_dashboard_history(database, days=365, max_points=300)
    actual = asyncio.run(
        worker_dashboard_history(SQLiteAsyncRepository(database), days=365, max_points=300)
    )
    assert actual == expected


def test_worker_buyback_forecast_matches_reference_exactly(tmp_path: Path) -> None:
    database = str(tmp_path / "worker-forecast.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_current_program(database)

    expected = reference_buyback_forecast(database, as_of_date="2026-08-17")
    actual = asyncio.run(
        worker_buyback_forecast(SQLiteAsyncRepository(database), as_of_date="2026-08-17")
    )

    assert actual == expected
    assert 61_000 <= actual["estimate"]["base_case_shares"] <= 63_000
    assert actual["methodology_version"] == "otec-buyback-safe-harbour-program-v1"


def test_worker_oslo_calendar_matches_reference() -> None:
    for start, end in (
        (date(2024, 3, 25), date(2024, 4, 5)),
        (date(2025, 12, 20), date(2026, 1, 5)),
        (date(2026, 3, 30), date(2026, 4, 10)),
        (date(2027, 5, 10), date(2027, 5, 25)),
    ):
        assert worker_oslo_days(start, end) == reference_oslo_days(start, end)


class _FakeResult:
    def __init__(self, results):
        self.results = results


class _FakeStatement:
    def __init__(self, database, sql):
        self.database = database
        self.sql = sql
        self.parameters = ()

    def bind(self, *parameters):
        self.parameters = parameters
        return self

    async def all(self):
        self.database.calls.append((self.sql, self.parameters))
        return _FakeResult([{"value": 7}])


class _FakeD1:
    def __init__(self):
        self.calls = []

    def prepare(self, sql):
        return _FakeStatement(self, sql)


def test_d1_repository_prepares_binds_and_normalizes_rows() -> None:
    database = _FakeD1()
    repository = D1Repository(database)
    row = asyncio.run(repository.first("SELECT ? AS value", (7,)))
    assert row == {"value": 7}
    assert database.calls == [("SELECT ? AS value", (7,))]
