from __future__ import annotations

import asyncio
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.bemobi_distribution_sync import sync_confirmed_bemobi_distribution_cash  # noqa: E402


class SQLiteAsyncWriteRepository:
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


def _fixture(tmp_path: Path, *, include_fx: bool = True) -> str:
    database = str(tmp_path / "bemobi-distribution-sync.db")
    init_database(database)
    with get_connection(database) as connection:
        source_id = _source_id(connection, "CVM")
        document_id = connection.execute(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, published_at, url, metadata_json
            ) VALUES (?, 'test-bemobi-jcp-2026-08', 'SHAREHOLDER_NOTICE',
                      'Test Bemobi JCP', '2026-08-12', 'https://example.invalid/jcp', '{}')
            """,
            (source_id,),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO bemobi_holdings(
                effective_from, effective_to, shares, ownership_pct, source_document_id, notes
            ) VALUES ('2026-08-17', NULL, 1000, '0.01', ?, 'Test holding')
            """,
            (document_id,),
        )
        connection.execute(
            """
            INSERT INTO corporate_actions(
                issuer_instrument_id, action_type, announcement_date, ex_date, record_date,
                payment_date, amount_per_share, total_amount, currency, source_document_id,
                notes, external_action_id, gross_amount_per_share, net_amount_per_share,
                gross_total_amount, net_total_amount, withholding_rate, tax_treatment
            ) VALUES (?, 'JCP', '2026-08-11', '2026-08-17', '2026-08-14',
                      '2026-08-28', '0.19178292', '16000000.00', 'BRL', ?,
                      'Test JCP', 'test-bemobi-2026-08-28-jcp', '0.19178292',
                      '0.15822091', '16000000.00', '13200000.00', '0.175', 'PUBLISHED_NET')
            """,
            (_instrument_id(connection, "BMOB3"), document_id),
        )
        if include_fx:
            connection.execute(
                """
                INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
                VALUES ('BRL', 'NOK', '2026-08-28T16:00:00Z', '1.8', ?)
                """,
                (_source_id(connection, "ECB"),),
            )
        connection.commit()
    return database


def test_confirmed_jcp_is_receivable_until_payment_then_net_cash(tmp_path: Path) -> None:
    database = _fixture(tmp_path)
    repository = SQLiteAsyncWriteRepository(database)

    before_payment = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-08-27")
    )
    assert before_payment["status"] == "ok"
    assert before_payment["actions_due"] == 0
    with get_connection(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cash_movements").fetchone()[0] == 0

    paid = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-08-28")
    )
    assert paid["status"] == "ok"
    assert paid["actions_due"] == 1
    assert paid["actions_processed"] == 1
    assert paid["rows_written"] == 2
    assert paid["rows_updated"] == 0

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT movement_type, amount_original, amount_nok, external_movement_id
            FROM cash_movements ORDER BY id
            """
        ).fetchall()

    receipt = next(row for row in rows if row["movement_type"] == "BEMOBI_JCP")
    tax = next(row for row in rows if row["movement_type"] == "TAX")
    assert Decimal(receipt["amount_original"]) == Decimal("191.78292000")
    assert Decimal(receipt["amount_nok"]) == Decimal("345.209256000")
    assert Decimal(tax["amount_original"]) == Decimal("-33.56201000")
    assert Decimal(tax["amount_nok"]) == Decimal("-60.411618000")
    assert tax["external_movement_id"] == "bemobi-withholding:test-bemobi-2026-08-28-jcp"
    assert Decimal(receipt["amount_nok"]) + Decimal(tax["amount_nok"]) == Decimal("284.797638000")

    again = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-08-28")
    )
    assert again["status"] == "ok"
    assert again["rows_written"] == 0
    assert again["rows_updated"] == 0
    assert again["rows_unchanged"] == 2
    with get_connection(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cash_movements").fetchone()[0] == 2


def test_due_distribution_without_payment_fx_is_not_guessed(tmp_path: Path) -> None:
    database = _fixture(tmp_path, include_fx=False)
    result = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(
            SQLiteAsyncWriteRepository(database),
            target_date="2026-08-28",
        )
    )

    assert result["status"] == "partial"
    assert result["rows_written"] == 0
    assert result["skipped"] == [
        {
            "corporate_action_id": result["skipped"][0]["corporate_action_id"],
            "external_action_id": "test-bemobi-2026-08-28-jcp",
            "payment_date": "2026-08-28",
            "reason": "missing_brl_nok",
        }
    ]
    with get_connection(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cash_movements").fetchone()[0] == 0


def test_future_dividend_uses_same_payment_lifecycle_without_withholding(tmp_path: Path) -> None:
    database = _fixture(tmp_path)
    with get_connection(database) as connection:
        document_id = connection.execute(
            "SELECT id FROM source_documents WHERE external_id='test-bemobi-jcp-2026-08'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO corporate_actions(
                issuer_instrument_id, action_type, ex_date, payment_date,
                amount_per_share, total_amount, currency, source_document_id,
                notes, external_action_id, gross_amount_per_share, gross_total_amount,
                tax_treatment
            ) VALUES (?, 'DIVIDEND', '2026-09-10', '2026-09-18',
                      '0.25', '20000000', 'BRL', ?, 'Future test dividend',
                      'test-bemobi-2026-09-18-dividend', '0.25', '20000000',
                      'NO_WITHHOLDING')
            """,
            (_instrument_id(connection, "BMOB3"), document_id),
        )
        connection.execute(
            """
            INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
            VALUES ('BRL', 'NOK', '2026-09-18T16:00:00Z', '2.0', ?)
            """,
            (_source_id(connection, "ECB"),),
        )
        connection.commit()

    result = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(
            SQLiteAsyncWriteRepository(database),
            target_date="2026-09-18",
        )
    )
    assert result["status"] == "ok"
    with get_connection(database) as connection:
        dividend = connection.execute(
            """
            SELECT movement_type, amount_original, amount_nok
            FROM cash_movements
            WHERE corporate_action_id=(
                SELECT id FROM corporate_actions
                WHERE external_action_id='test-bemobi-2026-09-18-dividend'
            )
            """
        ).fetchone()
        dividend_tax = connection.execute(
            """
            SELECT COUNT(*) FROM cash_movements
            WHERE external_movement_id='bemobi-withholding:test-bemobi-2026-09-18-dividend'
            """
        ).fetchone()[0]

    assert dividend["movement_type"] == "BEMOBI_DIVIDEND"
    assert Decimal(dividend["amount_original"]) == Decimal("250.00")
    assert Decimal(dividend["amount_nok"]) == Decimal("500.000")
    assert dividend_tax == 0
