from __future__ import annotations

import asyncio
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.db.connection import get_connection
from app.db.migration_runner import init_database

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.bemobi_distribution_sync import sync_confirmed_bemobi_distribution_cash  # noqa: E402
from src.nav_refresh import _receivable_actions, _receivable_for_day  # noqa: E402


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

    async def run_batch(self, statements):
        connection = self._connect()
        try:
            with connection:
                for sql, parameters in statements:
                    connection.execute(sql, parameters)
        finally:
            connection.close()


def _source_id(connection, code: str) -> int:
    return int(connection.execute("SELECT id FROM sources WHERE code=?", (code,)).fetchone()["id"])


def _instrument_id(connection, symbol: str) -> int:
    return int(connection.execute("SELECT id FROM instruments WHERE symbol=?", (symbol,)).fetchone()["id"])


def _fixture(
    tmp_path: Path, *, include_fx: bool = True, d1_schema: bool = False
) -> str:
    database = str(tmp_path / "bemobi-distribution-sync.db")
    if d1_schema:
        with sqlite3.connect(database) as connection:
            for migration in sorted((CLOUDFLARE / "migrations").glob("*.sql")):
                connection.executescript(migration.read_text(encoding="utf-8"))
    else:
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


@pytest.mark.parametrize("existing_payment", [False, True])
@pytest.mark.parametrize("failure_phase", ["read", "write"])
@pytest.mark.parametrize("d1_schema", [False, True])
def test_jcp_failure_preserves_complete_payment_and_retry_is_idempotent(
    tmp_path: Path, existing_payment: bool, failure_phase: str, d1_schema: bool
) -> None:
    database = _fixture(tmp_path, d1_schema=d1_schema)
    repository = SQLiteAsyncWriteRepository(database)
    if existing_payment:
        asyncio.run(
            sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-08-28")
        )

    with get_connection(database) as connection:
        before = [
            dict(row)
            for row in connection.execute("SELECT * FROM cash_movements ORDER BY id")
        ]
        # A corrected FX rate must update both sides of an existing net payment.
        connection.execute("UPDATE fx_rates SET rate='2' WHERE base_currency='BRL'")
        if failure_phase == "write":
            for operation in ("INSERT", "UPDATE"):
                connection.execute(
                    f"""
                    CREATE TRIGGER fail_tax_{operation.lower()}
                    BEFORE {operation} ON cash_movements
                    WHEN NEW.movement_type='TAX'
                    BEGIN
                        SELECT RAISE(ABORT, 'temporary withholding failure');
                    END
                    """
                )
        connection.commit()

    class FailingReadRepository(SQLiteAsyncWriteRepository):
        async def first(self, sql: str, parameters=()):
            if "WHERE external_movement_id=?" in sql:
                raise sqlite3.OperationalError("temporary withholding failure")
            return await super().first(sql, parameters)

    failing = FailingReadRepository(database) if failure_phase == "read" else repository
    with pytest.raises(sqlite3.DatabaseError, match="temporary withholding failure"):
        asyncio.run(
            sync_confirmed_bemobi_distribution_cash(failing, target_date="2026-08-28")
        )

    with get_connection(database) as connection:
        after = [
            dict(row)
            for row in connection.execute("SELECT * FROM cash_movements ORDER BY id")
        ]
        assert after == before
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        if failure_phase == "write":
            connection.execute("DROP TRIGGER fail_tax_insert")
            connection.execute("DROP TRIGGER fail_tax_update")
        connection.commit()

    retried = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-08-28")
    )
    assert retried["rows_updated" if existing_payment else "rows_written"] == 2
    with get_connection(database) as connection:
        rows = connection.execute("SELECT amount_nok FROM cash_movements").fetchall()
        assert len(rows) == 2
        assert sum(Decimal(row["amount_nok"]) for row in rows) == Decimal("316.44182000")

    again = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-08-28")
    )
    assert again["rows_written"] == again["rows_updated"] == 0
    assert again["rows_unchanged"] == 2


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


@pytest.mark.parametrize("d1_schema", [False, True])
@pytest.mark.parametrize("payment_fx", ["1.7736", "1.81"])
def test_q3_2026_jcp_payment_reconciles_receivable_to_net_cash(
    tmp_path: Path, d1_schema: bool, payment_fx: str
) -> None:
    """Real Q3 terms; simulated FX and holdings, not proof of actual receipt."""
    database = _fixture(tmp_path, include_fx=False, d1_schema=d1_schema)
    repository = SQLiteAsyncWriteRepository(database)
    external_id = "test-bemobi-2026-11-30-jcp-3q26"
    shares = Decimal("32719588")
    gross_brl = shares * Decimal("0.19178292")
    net_brl = shares * Decimal("0.15822091")
    tax_brl = net_brl - gross_brl
    prior_fx = Decimal("1.7736")
    settlement_fx = Decimal(payment_fx)
    with get_connection(database) as connection:
        connection.execute(
            """UPDATE corporate_actions SET announcement_date='2026-11-12',
               record_date='2026-11-17', ex_date='2026-11-18',
               payment_date='2026-11-30', external_action_id=?
               WHERE external_action_id='test-bemobi-2026-08-28-jcp'""",
            (external_id,),
        )
        action = connection.execute(
            "SELECT id, source_document_id FROM corporate_actions WHERE external_action_id=?",
            (external_id,),
        ).fetchone()
        connection.execute(
            """UPDATE bemobi_holdings SET effective_from='2026-11-17',
               effective_to='2026-11-18', shares=? WHERE source_document_id=?""",
            (int(shares), action["source_document_id"]),
        )
        # Entitlement is based on the holding at ex-date, not the later holding.
        connection.execute(
            """INSERT INTO bemobi_holdings(effective_from, effective_to, shares,
               ownership_pct, source_document_id, notes)
               VALUES ('2026-11-19', NULL, 1000, '0.01', ?, 'Simulated post-ex holding')""",
            (action["source_document_id"],),
        )
        for day in ("2026-11-18", "2026-11-27"):
            connection.execute(
                """INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
                   VALUES ('BRL', 'NOK', ?, ?, ?)""",
                (f"{day}T16:00:00Z", str(prior_fx), _source_id(connection, "NORGES_BANK")),
            )
        connection.commit()

    actions = asyncio.run(_receivable_actions(repository))
    assert len(actions) == 1
    assert actions[0]["id"] == action["id"]
    assert actions[0]["holding_shares"] == int(shares)

    for day in ("2026-11-17", "2026-11-30", "2026-12-01"):
        assert asyncio.run(_receivable_for_day(repository, day, actions)) == (
            Decimal("0"), "NONE", [],
        )
    for day in ("2026-11-18", "2026-11-27", "2026-11-29"):
        receivable, quality, components = asyncio.run(_receivable_for_day(repository, day, actions))
        assert abs(receivable - net_brl * prior_fx) < Decimal("0.000001")
        assert quality == "ESTIMATED_NET"
        assert len(components) == 1
        assert components[0]["calibration"]["basis"] == "PUBLISHED_NET"
        assert components[0]["calibration"]["shareholder_specific_tax_confirmed"] is False
        assert components[0]["calibration"]["source_document_id"] == action["source_document_id"]

    before = asyncio.run(sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-11-29"))
    assert before["actions_due"] == 0
    with get_connection(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cash_movements").fetchone()[0] == 0

    # If the same-day rate is not yet published, the existing lookback policy
    # uses the last available rate. A later rate must update both cash rows.
    initial = asyncio.run(sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-11-30"))
    assert initial["status"] == "ok"
    assert initial["rows_written"] == 2
    with get_connection(database) as connection:
        rows = connection.execute("SELECT amount_nok FROM cash_movements").fetchall()
        assert sum(Decimal(row["amount_nok"]) for row in rows) == net_brl * prior_fx
        connection.execute(
            """INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
               VALUES ('BRL', 'NOK', '2026-11-30T16:00:00Z', ?, ?)""",
            (payment_fx, _source_id(connection, "NORGES_BANK")),
        )
        connection.commit()

    paid = asyncio.run(sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-11-30"))
    assert paid["status"] == "ok"
    assert paid["rows_written"] == 0
    assert paid["rows_updated"] == (0 if settlement_fx == prior_fx else 2)
    with get_connection(database) as connection:
        rows = connection.execute("SELECT * FROM cash_movements ORDER BY id").fetchall()
    assert len(rows) == 2
    receipt = next(row for row in rows if row["movement_type"] == "BEMOBI_JCP")
    tax = next(row for row in rows if row["movement_type"] == "TAX")
    for row in rows:
        assert row["movement_date"] == "2026-11-30"
        assert row["confidence"] == "ESTIMATED"
        assert row["source_document_id"] == action["source_document_id"]
        assert Decimal(row["fx_rate_to_nok"]) == settlement_fx
    assert receipt["corporate_action_id"] == action["id"]
    assert tax["external_movement_id"] == f"bemobi-withholding:{external_id}"
    assert Decimal(receipt["amount_original"]) == gross_brl
    assert Decimal(tax["amount_original"]) == tax_brl
    assert "PUBLISHED_NET" in tax["description"]
    net_cash = Decimal(receipt["amount_nok"]) + Decimal(tax["amount_nok"])
    assert net_cash == net_brl * settlement_fx
    # Isolate the JCP component: payment itself is not an increase in NAV.
    # Any difference versus the prior receivable is solely FX in this fixture.
    assert net_cash - net_brl * prior_fx == net_brl * (settlement_fx - prior_fx)
    assert asyncio.run(_receivable_for_day(repository, "2026-11-30", actions))[0] == 0

    again = asyncio.run(sync_confirmed_bemobi_distribution_cash(repository, target_date="2026-12-01"))
    assert again["rows_written"] == again["rows_updated"] == 0
    assert again["rows_unchanged"] == 2
    with get_connection(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cash_movements").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
