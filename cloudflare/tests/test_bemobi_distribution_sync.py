from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from bemobi_distribution_sync import sync_confirmed_bemobi_distribution_cash  # noqa: E402


class SQLiteRepository:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row

    async def all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(sql, params).fetchall()]

    async def first(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        row = self.connection.execute(sql, params).fetchone()
        return None if row is None else dict(row)

    async def run(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.connection.execute(sql, params)


def test_distribution_cash_prefers_explicit_gross_amount_per_share() -> None:
    repository = SQLiteRepository()
    repository.connection.executescript(
        """
        CREATE TABLE instruments(id INTEGER PRIMARY KEY, symbol TEXT NOT NULL);
        CREATE TABLE corporate_actions(
            id INTEGER PRIMARY KEY,
            issuer_instrument_id INTEGER NOT NULL,
            external_action_id TEXT,
            action_type TEXT NOT NULL,
            ex_date TEXT,
            payment_date TEXT,
            amount_per_share TEXT,
            gross_amount_per_share TEXT,
            net_amount_per_share TEXT,
            withholding_rate TEXT,
            tax_treatment TEXT,
            source_document_id INTEGER
        );
        CREATE TABLE bemobi_holdings(
            id INTEGER PRIMARY KEY,
            shares INTEGER NOT NULL,
            effective_from TEXT NOT NULL,
            effective_to TEXT
        );
        CREATE TABLE sources(id INTEGER PRIMARY KEY, code TEXT NOT NULL);
        CREATE TABLE fx_rates(
            id INTEGER PRIMARY KEY,
            base_currency TEXT NOT NULL,
            quote_currency TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            rate TEXT NOT NULL,
            source_document_id INTEGER,
            source_id INTEGER NOT NULL
        );
        CREATE TABLE cash_movements(
            id INTEGER PRIMARY KEY,
            movement_date TEXT,
            movement_type TEXT,
            amount_nok TEXT,
            amount_original TEXT,
            currency TEXT,
            fx_rate_to_nok TEXT,
            description TEXT,
            source_document_id INTEGER,
            confidence TEXT,
            corporate_action_id INTEGER,
            external_movement_id TEXT
        );

        INSERT INTO instruments VALUES (1, 'BMOB3');
        INSERT INTO sources VALUES (1, 'NORGES_BANK');
        INSERT INTO bemobi_holdings VALUES (1, 10, '2026-01-01', NULL);
        INSERT INTO fx_rates VALUES (
            1, 'BRL', 'NOK', '2026-06-30T00:00:00Z', '2', 3, 1
        );
        INSERT INTO corporate_actions VALUES (
            1, 1, 'jcp-1', 'JCP', '2026-06-01', '2026-06-30',
            '0.85', '1.00', '0.85', NULL, 'JCP', 4
        );
        """
    )

    result = asyncio.run(
        sync_confirmed_bemobi_distribution_cash(
            repository,
            target_date="2026-06-30",
        )
    )

    rows = repository.connection.execute(
        "SELECT movement_type, amount_original, amount_nok "
        "FROM cash_movements ORDER BY movement_type"
    ).fetchall()
    assert result["status"] == "ok"
    assert [tuple(row) for row in rows] == [
        ("BEMOBI_JCP", "10.00", "20.00"),
        ("TAX", "-1.50", "-3.00"),
    ]
