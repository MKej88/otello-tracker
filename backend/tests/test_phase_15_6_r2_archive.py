from __future__ import annotations

import asyncio
import gzip
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from newsweb_buybacks import BuybackStatus  # noqa: E402
from newsweb_daily_buybacks import (  # noqa: E402
    parse_buyback_transaction_text,
    sync_daily_buyback_cash,
    validate_daily_buybacks,
)
from r2_archive import archive_bytes, raw_object_key  # noqa: E402
from r2_snapshot import SNAPSHOT_VERSION, archive_d1_snapshot  # noqa: E402

from app.db.connection import get_connection  # noqa: E402
from app.db.migration_runner import init_database  # noqa: E402
from app.db.repository import create_source_document  # noqa: E402


class _Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, payload: bytes):
        self.objects[key] = bytes(payload)
        return {"key": key}


def test_content_addressed_r2_key_is_deterministic_and_sanitized() -> None:
    payload = b"same-source-payload"
    bucket = _Bucket()
    first = asyncio.run(
        archive_bytes(
            bucket,
            payload,
            source="NewsWeb",
            kind="buyback pdf",
            logical_date="2026-08-17",
            filename="Transaksjonsoversikt #1.pdf",
        )
    )
    second = asyncio.run(
        archive_bytes(
            bucket,
            payload,
            source="NewsWeb",
            kind="buyback pdf",
            logical_date="2026-08-17",
            filename="Transaksjonsoversikt #1.pdf",
        )
    )
    assert first["r2_key"] == second["r2_key"]
    assert first["content_sha256"] == second["content_sha256"]
    assert " " not in first["r2_key"]
    assert "#" not in first["r2_key"]
    assert len(bucket.objects) == 1

    key = raw_object_key(
        source="B3",
        kind="COTAHIST daily",
        logical_date="2026-08-17",
        digest=first["content_sha256"],
        filename="COTAHIST_D17082026.ZIP",
    )
    assert key.startswith("raw/b3/cotahist-daily/2026-08-17/")


def test_worker_buyback_parser_and_weekly_reconciliation() -> None:
    text = "\n".join(
        [
            "B OTEC 100 17,50 1750,00 13.08.2026 10:00:00",
            "B OTEC 200 18,00 3600,00 14.08.2026 11:00:00",
            "ExecBuy 100",
            "ExecBuy 200",
        ]
    )
    daily = parse_buyback_transaction_text(text)
    assert [(item.trade_date, item.shares) for item in daily] == [
        ("2026-08-13", 100),
        ("2026-08-14", 200),
    ]
    weekly = BuybackStatus(
        program_reference_date="2026-08-10",
        period_start="2026-08-10",
        period_end="2026-08-14",
        period_shares=300,
        period_avg_price_nok=(daily[0].amount_nok + daily[1].amount_nok) / 300,
        period_amount_nok=daily[0].amount_nok + daily[1].amount_nok,
        cumulative_program_shares=300,
        cumulative_program_avg_price_nok=(daily[0].amount_nok + daily[1].amount_nok) / 300,
        cumulative_program_amount_nok=daily[0].amount_nok + daily[1].amount_nok,
        max_program_shares=1_000_000,
        treasury_shares_after=300,
    )
    validation = validate_daily_buybacks(daily, weekly)
    assert validation["quality"] == "CONFIRMED"
    assert validation["shares"] == 300
    assert validation["amount_nok"] == "5350.00"


class _SQLiteAsyncWriteRepository:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    def _connect(self):
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
            return {"rowcount": cursor.rowcount}
        finally:
            connection.close()


def test_daily_buyback_cash_replaces_weekly_fallback(tmp_path: Path) -> None:
    database = str(tmp_path / "daily-cash.db")
    init_database(database)
    with get_connection(database) as connection:
        document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="test-phase-15-6-buyback",
            document_type="BUYBACK_TRANSACTION_ATTACHMENT",
            title="test",
            url="https://example.test/test.pdf",
            content_sha256="a" * 64,
        )
        connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, max_shares,
                status, source_document_id
            ) VALUES ('test-program', '2026-08-10T00:00:00Z', '2026-08-10', 1000000,
                      'ACTIVE', ?)
            """,
            (document_id,),
        )
        program_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO buybacks(
                program_id, period_start, trade_date, shares, avg_price_nok,
                amount_nok, cumulative_program_shares,
                cumulative_program_avg_price_nok, cumulative_program_amount_nok,
                treasury_shares_after, source_document_id
            ) VALUES (?, '2026-08-10', '2026-08-14', 300, '10', '3000',
                      300, '10', '3000', 300, ?)
            """,
            (program_id, document_id),
        )
        buyback_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, amount_original, currency,
                fx_rate_to_nok, description, source_document_id, confidence, buyback_id
            ) VALUES ('2026-08-14', 'OTELLO_BUYBACK', '-3000', '-3000', 'NOK', '1',
                      'weekly fallback', ?, 'CONFIRMED', ?)
            """,
            (document_id, buyback_id),
        )
        connection.executemany(
            """
            INSERT INTO buyback_daily_transactions(
                weekly_buyback_id, trade_date, shares, avg_price_nok, amount_nok,
                trade_count, source_document_id, quality
            ) VALUES (?, ?, ?, '10', ?, 1, ?, 'CONFIRMED')
            """,
            [
                (buyback_id, "2026-08-13", 100, "1000", document_id),
                (buyback_id, "2026-08-14", 200, "2000", document_id),
            ],
        )
        connection.commit()

    result = asyncio.run(
        sync_daily_buyback_cash(
            _SQLiteAsyncWriteRepository(database),
            weekly_buyback_id=buyback_id,
        )
    )
    assert result["weeks_synced"] == 1
    assert result["weekly_cash_rows_deleted"] == 1
    assert result["daily_cash_rows_written"] == 2

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT movement_date, movement_type, amount_nok
            FROM cash_movements
            WHERE buyback_id=? ORDER BY movement_date
            """,
            (buyback_id,),
        ).fetchall()
    assert [(row["movement_date"], row["movement_type"], row["amount_nok"]) for row in rows] == [
        ("2026-08-13", "OTELLO_BUYBACK_DAILY", "-1000"),
        ("2026-08-14", "OTELLO_BUYBACK_DAILY", "-2000"),
    ]


class _SnapshotRepository:
    async def all(self, sql: str, parameters=()):
        table = sql.split("FROM ", 1)[1].split(" ", 1)[0]
        return [{"table": table, "id": 1, "value": "x"}]


def test_d1_logical_snapshot_is_reproducible_and_manifested() -> None:
    bucket = _Bucket()
    result = asyncio.run(
        archive_d1_snapshot(
            _SnapshotRepository(),
            bucket,
            target_date="2026-08-17",
            preflight_status="READY",
        )
    )
    assert result["status"] == "ok"
    assert result["snapshot_version"] == SNAPSHOT_VERSION
    assert result["snapshot_key"] in bucket.objects
    assert result["manifest_key"] in bucket.objects

    decoded = json.loads(gzip.decompress(bucket.objects[result["snapshot_key"]]))
    assert decoded["snapshot_version"] == SNAPSHOT_VERSION
    assert decoded["target_date"] == "2026-08-17"
    assert "nav_snapshots" in decoded["tables"]
    manifest = json.loads(bucket.objects[result["manifest_key"]])
    assert manifest["logical_sha256"] == result["logical_sha256"]
    assert manifest["preflight_status"] == "READY"
    assert "NOT_D1_TIME_TRAVEL_REPLACEMENT" in manifest["restore_scope"]


def test_phase_15_6_worker_config_bundles_pdf_parser_and_archive_steps() -> None:
    pyproject = (ROOT / "cloudflare" / "pyproject.toml").read_text(encoding="utf-8")
    assert '"pypdf==6.16.1"' in pyproject

    entry = (ROOT / "cloudflare" / "src" / "entry.py").read_text(encoding="utf-8")
    assert '"archive NewsWeb buyback PDFs"' in entry
    assert '"archive D1 logical snapshot"' in entry
    assert "archive_bucket=self.env.SOURCE_ARCHIVE" in entry
