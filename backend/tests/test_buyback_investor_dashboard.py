from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

from app.buybacks.activity import seed_otec_activity_history
from app.buybacks.dashboard import buyback_dashboard as reference_dashboard
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
CLOUDFLARE_SRC = CLOUDFLARE / "src"
for path in (CLOUDFLARE, CLOUDFLARE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from buyback_dashboard import buyback_dashboard as worker_dashboard  # noqa: E402


class SQLiteAsyncRepository:
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
            external_id="investor-dashboard-current-program",
            document_type="REGULATORY_NEWS",
            title="Investor dashboard current program",
            url="https://newsweb.oslobors.no/message/investor-dashboard",
        )
        cursor = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, end_date,
                max_shares, max_price_nok, status, source_document_id, notes
            ) VALUES ('otec-buyback-2026-06-08', '2026-06-08T00:00:00Z',
                      '2026-06-08', '2026-12-31', 2192046, '20', 'ACTIVE', ?, 'test')
            """,
            (document_id,),
        )
        program_id = int(cursor.lastrowid)
        for start, end, shares, cumulative in weeks:
            amount = shares * 17
            connection.execute(
                """
                INSERT INTO buybacks(
                    program_id, period_start, trade_date, shares, avg_price_nok, amount_nok,
                    cumulative_program_shares, cumulative_program_amount_nok,
                    treasury_shares_after, source_document_id
                ) VALUES (?, ?, ?, ?, '17', ?, ?, ?, ?, ?)
                """,
                (
                    program_id,
                    start,
                    end,
                    shares,
                    str(amount),
                    cumulative,
                    str(cumulative * 17),
                    5_000_000 + cumulative,
                    document_id,
                ),
            )
        connection.execute(
            """
            INSERT INTO otello_share_counts(
                effective_from, total_shares, treasury_shares, outstanding_shares,
                source_document_id, notes
            ) VALUES ('2026-06-08', 91200000, 5000000, 86200000, ?, 'test share count')
            """,
            (document_id,),
        )
        connection.execute("""
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, bemobi_value_nok,
                cash_estimate_nok, other_net_assets_nok, shares_outstanding,
                calculation_version, inputs_hash, status, nav_scope
            ) VALUES (
                '2026-08-17T16:30:00Z', '1700000000', '19.86', '1200000000',
                '500000000', '0', 85599607, 'full-market-nav-daily-v2',
                'full-nav-test', 'OK', 'FULL'
            )
            """)
        connection.execute("""
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, bemobi_value_nok,
                cash_estimate_nok, other_net_assets_nok, shares_outstanding,
                calculation_version, inputs_hash, status, nav_scope
            ) VALUES (
                '2026-06-08T16:30:00Z', '1680000000', '19.49', '1180000000',
                '500000000', '0', 86200000, 'full-market-nav-daily-v2',
                'full-nav-program-start', 'OK', 'FULL'
            )
            """)
        connection.execute("""
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, bemobi_value_nok,
                cash_estimate_nok, other_net_assets_nok, shares_outstanding,
                calculation_version, inputs_hash, status, nav_scope
            ) VALUES (
                '2026-08-17T16:30:00Z', '900000000', '10.51', '400000000',
                '500000000', '0', 85599607, 'core-nav-daily-v1',
                'core-nav-test', 'OK', 'CORE'
            )
            """)
        connection.commit()


def _database(tmp_path: Path) -> str:
    database = str(tmp_path / "buyback-investor.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_current_program(database)
    return database


def test_buyback_dashboard_is_shareholder_focused_and_volume_backed(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    result = reference_dashboard(database, as_of_date="2026-08-17")

    assert result["ready"] is True
    assert result["program"]["cumulative_shares"] == 600_393
    assert result["program"]["remaining_shares"] == 1_591_653
    assert result["program"]["progress_pct"] == 27.4
    assert result["program"]["average_purchase_price_nok"] == "17"
    assert result["program"]["vwap_nok"] == "17"
    assert result["latest_week"]["shares"] == 59_512
    assert result["latest_week"]["market_volume_shares"] > 59_512
    # Weekly market share is a descriptive ratio, not the Safe Harbour legal test.
    # The 25% limit is assessed per purchase day against prior-20-day ADV.
    assert 0 < result["latest_week"]["volume_share_pct"] < 100
    assert result["latest_week"]["safe_harbour_capacity_shares"] > 0
    assert result["latest_week"]["safe_harbour_utilization_pct"] > 0
    assert result["shares"]["treasury_shares"] == 5_600_393
    assert result["shares"]["outstanding_shares"] == 85_599_607
    assert result["shares"]["treasury_source"] == "LATEST_BUYBACK"
    assert result["forecast"]["estimate"]["base_case_shares"] > 0
    assert result["backtest"]["metrics"]["weeks"] >= 8
    assert len(result["backtest"]["weeks"]) == 8
    assert all(
        item["actual_volume_share_pct"] is not None
        for item in result["backtest"]["weeks"]
    )
    assert result["completion"]["estimated_weeks_remaining"] is not None
    assert result["completion"]["estimated_completion_date"] is not None


def test_worker_buyback_dashboard_matches_reference_exactly(tmp_path: Path) -> None:
    database = _database(tmp_path)
    expected = reference_dashboard(database, as_of_date="2026-08-17")
    actual = asyncio.run(
        worker_dashboard(SQLiteAsyncRepository(database), as_of_date="2026-08-17")
    )
    assert actual == expected


def test_latest_week_metrics_do_not_depend_on_forecast_history(tmp_path: Path) -> None:
    database = _database(tmp_path)
    expected = reference_dashboard(database, as_of_date="2026-08-29")
    latest = expected["latest_week"]
    assert latest["market_volume_shares"] is not None
    assert latest["volume_share_pct"] is not None
    assert latest["safe_harbour_capacity_shares"] is not None
    assert latest["safe_harbour_utilization_pct"] is not None

    actual = asyncio.run(
        worker_dashboard(SQLiteAsyncRepository(database), as_of_date="2026-08-29")
    )
    assert actual == expected


def test_nav_effect_uses_full_nav_snapshot(tmp_path: Path) -> None:
    database = _database(tmp_path)

    reference = reference_dashboard(database, as_of_date="2026-08-17")
    worker = asyncio.run(
        worker_dashboard(SQLiteAsyncRepository(database), as_of_date="2026-08-17")
    )

    assert reference["nav_effect"] == {
        "per_share_nok": 0.0199,
        "pct": 0.1004,
    }
    assert worker["nav_effect"] == reference["nav_effect"]


def test_program_status_uses_active_program_cumulative_facts(tmp_path: Path) -> None:
    database = _database(tmp_path)

    reference = reference_dashboard(database, as_of_date="2026-08-17")
    program = reference["program"]

    assert program["cumulative_shares"] == 600_393
    assert program["vwap_nok"] == "17"
    assert program["cash_spent_nok"] == -10_206_681
    assert program["share_count_nav_effect_per_share_nok"] == 0.13751285161489648

    worker = asyncio.run(
        worker_dashboard(SQLiteAsyncRepository(database), as_of_date="2026-08-17")
    )
    assert worker["program"] == program


def test_program_status_excludes_older_program_and_uses_weighted_price(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with get_connection(database) as connection:
        latest_id = connection.execute(
            "SELECT id FROM buybacks ORDER BY trade_date DESC, id DESC LIMIT 1"
        ).fetchone()["id"]
        connection.execute(
            """
            UPDATE buybacks
            SET cumulative_program_amount_nok = '10807074',
                cumulative_program_avg_price_nok = NULL
            WHERE id = ?
            """,
            (latest_id,),
        )
        program_document_id = connection.execute(
            "SELECT source_document_id FROM buyback_programs LIMIT 1"
        ).fetchone()["source_document_id"]
        old_program_id = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, end_date,
                status, source_document_id
            ) VALUES ('old-program', '2025-01-01', '2025-01-01', '2025-12-31',
                      'COMPLETED', ?)
            """,
            (program_document_id,),
        ).lastrowid
        document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="old-program-late-row",
            document_type="REGULATORY_NEWS",
            title="Old program late row",
            url="https://newsweb.oslobors.no/message/old-program-late-row",
        )
        connection.execute(
            """
            INSERT INTO buybacks(
                program_id, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, cumulative_program_amount_nok,
                source_document_id
            ) VALUES (?, '2026-08-17', 999999, '99', '98999901',
                      999999, '98999901', ?)
            """,
            (old_program_id, document_id),
        )
        connection.commit()

    result = reference_dashboard(database, as_of_date="2026-08-17")

    assert result["program"]["cumulative_shares"] == 600_393
    assert result["program"]["vwap_nok"] == "18"
    assert result["program"]["cash_spent_nok"] == -10_807_074


def test_overview_buyback_card_has_program_status_and_null_guards() -> None:
    page = (ROOT / "frontend/src/OverviewPage.tsx").read_text(encoding="utf-8")

    for label in (
        "Siste rapporterte kjøp",
        "Neste uke – baseestimat",
        "Estimatintervall",
        "Kjøpt siden programstart",
        "Gjennomsnittlig kjøpskurs",
        "Kontantbruk hittil",
        "NAV-effekt fra færre aksjer",
    ):
        assert label in page
    assert 'className="overviewBuybackDivider"' in page
    assert "finiteNumber" in page
    assert "return Number.isFinite(parsed) ? parsed : null" in page
