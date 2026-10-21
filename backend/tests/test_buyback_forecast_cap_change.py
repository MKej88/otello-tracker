"""Forecast stays forward-looking when Otello raises its cap after zero-buy weeks."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

from app.buybacks.activity import seed_otec_activity_history
from app.buybacks.forecast import buyback_forecast as reference_forecast
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document

ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT / "cloudflare", ROOT / "cloudflare" / "src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from src.buyback_service import buyback_forecast as worker_forecast  # noqa: E402

from test_buyback_weekend_continuity import _seed_program  # noqa: E402


class SQLiteAsyncRepository:
    def __init__(self, database: str):
        self.database = database

    async def all(self, query: str, args=()):
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, args).fetchall()]

    async def first(self, query: str, args=()):
        rows = await self.all(query, args)
        return rows[0] if rows else None


def test_amended_price_never_recalculates_past_week_as_new_forecast(tmp_path):
    database = str(tmp_path / "buyback-cap-change.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_program(database)

    with get_connection(database) as connection:
        program = connection.execute(
            "SELECT id, source_document_id FROM buyback_programs WHERE status='ACTIVE'"
        ).fetchone()
        amendment = create_source_document(
            connection, source_code="NEWSWEB",
            external_id="buyback-cap-amendment-test",
            document_type="REGULATORY_NEWS",
            title="Share Buyback Program - update",
            url="https://newsweb.oslobors.no/message/buyback-cap-amendment-test",
            published_at="2026-08-24T06:00:00Z",
        )
        create_source_document(
            connection, source_code="NEWSWEB",
            external_id="buyback-zero-week-test",
            document_type="REGULATORY_NEWS",
            title="Share Buyback Program Status",
            url="https://newsweb.oslobors.no/message/buyback-zero-week-test",
            published_at="2026-08-23T17:00:00Z",
            metadata={
                "buyback_status": "NO_PURCHASES",
                # Old archived notices have period_text but no structured period_end.
                "period_text": "From 17 August 2026 through 21 August 2026, Otello did not buy any shares",
            },
        )
        connection.execute(
            """INSERT INTO buyback_program_cap_history(
                  program_id, effective_at, max_price_nok, source_document_id, event_kind
               ) VALUES (?, '2026-06-08T00:00:00Z', '20', ?, 'BASELINE')""",
            (program["id"], program["source_document_id"]),
        )
        connection.execute(
            """INSERT INTO buyback_program_cap_history(
                  program_id, effective_at, max_price_nok, source_document_id, event_kind
               ) VALUES (?, '2026-08-24T06:00:00Z', '25', ?, 'AMENDMENT')""",
            (program["id"], amendment),
        )
        connection.execute(
            "UPDATE buyback_programs SET max_price_nok='25' WHERE id=?",
            (program["id"],),
        )
        connection.commit()

    # 20 August: cap increase and zero-purchase report were not yet available.
    old = reference_forecast(database, as_of_date="2026-08-20")
    assert old["ready"]
    assert old["price_model"]["program_cap_nok"] == 20.0
    assert old["latest_reported_period_end"] == "2026-08-14"
    assert old["forecast_week"]["from"] == "2026-08-24"

    # 26 August: the week has started, so the next *whole* week is targeted.
    current = reference_forecast(database, as_of_date="2026-08-26")
    worker = asyncio.run(worker_forecast(
        SQLiteAsyncRepository(database), as_of_date="2026-08-26"
    ))
    assert worker == current
    assert current["ready"]
    assert current["price_model"]["program_cap_nok"] == 25.0
    assert current["latest_reported_period_end"] == "2026-08-21"
    assert current["forecast_week"]["from"] == "2026-08-31"
    assert current["forecast_week"]["to"] == "2026-09-04"
    assert current["forecast_basis"] == "NEXT_FULL_UNSTARTED_WEEK"
    assert current["awaiting_program_update"] is False
    assert current["volume_model"]["volume_through"] <= "2026-08-26"
