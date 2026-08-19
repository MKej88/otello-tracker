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
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.buyback_dashboard import buyback_dashboard as worker_dashboard  # noqa: E402


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
        connection.commit()


def _database(tmp_path: Path) -> str:
    database = str(tmp_path / "buyback-investor.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_current_program(database)
    return database


def test_buyback_dashboard_is_shareholder_focused_and_volume_backed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    result = reference_dashboard(database, as_of_date="2026-08-17")

    assert result["ready"] is True
    assert result["program"]["cumulative_shares"] == 600_393
    assert result["program"]["remaining_shares"] == 1_591_653
    assert result["program"]["progress_pct"] == 27.4
    assert result["latest_week"]["shares"] == 59_512
    assert result["latest_week"]["market_volume_shares"] > 59_512
    assert 0 < result["latest_week"]["volume_share_pct"] < 25
    assert result["latest_week"]["safe_harbour_capacity_shares"] > 0
    assert result["shares"]["treasury_shares"] == 5_600_393
    assert result["shares"]["outstanding_shares"] == 85_599_607
    assert result["shares"]["treasury_source"] == "LATEST_BUYBACK"
    assert result["forecast"]["estimate"]["base_case_shares"] > 0
    assert result["backtest"]["metrics"]["weeks"] >= 8
    assert len(result["backtest"]["weeks"]) == 8
    assert all(item["actual_volume_share_pct"] is not None for item in result["backtest"]["weeks"])
    assert result["completion"]["estimated_weeks_remaining"] is not None
    assert result["completion"]["estimated_completion_date"] is not None


def test_worker_buyback_dashboard_matches_reference_exactly(tmp_path: Path) -> None:
    database = _database(tmp_path)
    expected = reference_dashboard(database, as_of_date="2026-08-17")
    actual = asyncio.run(
        worker_dashboard(SQLiteAsyncRepository(database), as_of_date="2026-08-17")
    )
    assert actual == expected
