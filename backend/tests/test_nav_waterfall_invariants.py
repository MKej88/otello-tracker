from __future__ import annotations

import asyncio
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

from app.nav_waterfall import _modeled_buyback_cash as reference_buyback_cash

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from nav_waterfall import _modeled_buyback_cash as worker_buyback_cash  # noqa: E402


def test_transaction_level_buybacks_reconcile_without_weekly_double_count() -> None:
    daily_rows = [
        {
            "movement_date": "2026-08-11",
            "amount_nok": "-1720.00",
            "description": "NewsWeb transaction-level Otello buyback",
        },
        {
            "movement_date": "2026-08-12",
            "amount_nok": "-3440.00",
            "description": "NewsWeb transaction-level Otello buyback",
        },
    ]
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE cash_movements (
            id INTEGER PRIMARY KEY,
            movement_date TEXT NOT NULL,
            movement_type TEXT NOT NULL,
            amount_nok TEXT NOT NULL,
            description TEXT,
            buyback_id INTEGER
        )
        """)
    connection.executemany(
        """
        INSERT INTO cash_movements(
            movement_date, movement_type, amount_nok, description, buyback_id
        ) VALUES (
            :movement_date, 'OTELLO_BUYBACK_DAILY', :amount_nok, :description, 7
        )
        """,
        daily_rows,
    )
    connection.execute("""
        INSERT INTO cash_movements(
            movement_date, movement_type, amount_nok, description, buyback_id
        ) VALUES (
            '2026-08-12', 'OTELLO_BUYBACK', '-5160.00',
            'Otello buyback during 2026-08-11–2026-08-12', 7
        )
        """)

    reference = reference_buyback_cash(
        connection,
        anchor_date="2026-08-10",
        as_of_date="2026-08-12",
    )

    class Repository:
        async def all(self, query, _params):
            assert "OTELLO_BUYBACK_DAILY" in query
            return daily_rows

    worker = asyncio.run(
        worker_buyback_cash(
            Repository(),
            anchor_date="2026-08-10",
            as_of_date="2026-08-12",
        )
    )

    assert reference == worker
    assert reference["amount_nok"] == Decimal("-5160.00")
    assert reference["movement_count"] == 2
