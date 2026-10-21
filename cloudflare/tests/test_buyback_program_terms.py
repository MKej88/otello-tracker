"""Regressions for official buyback cap changes, history and price extraction."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from buyback_program_terms import (  # noqa: E402
    ingest_program_cap_amendment,
    is_program_update_title,
    parse_amended_price_cap,
    record_program_price_cap,
)
from newsweb_client import NewsWebMessage  # noqa: E402


class SQLiteRepository:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE source_documents(
                id INTEGER PRIMARY KEY,
                external_id TEXT UNIQUE,
                title TEXT,
                published_at TEXT
            );
            CREATE TABLE buyback_programs(
                id INTEGER PRIMARY KEY,
                external_program_id TEXT,
                start_date TEXT,
                status TEXT,
                max_price_nok TEXT,
                source_document_id INTEGER
            );
            CREATE TABLE buyback_program_cap_history(
                id INTEGER PRIMARY KEY,
                program_id INTEGER,
                effective_at TEXT,
                max_price_nok TEXT,
                source_document_id INTEGER,
                event_kind TEXT,
                UNIQUE(program_id, source_document_id)
            );
            INSERT INTO source_documents(id, external_id) VALUES
              (10, 'old-program-source'), (21, 'old-weekly-source');
            INSERT INTO buyback_programs VALUES
              (1, 'otec-buyback-2026-06-08', '2026-06-08', 'ACTIVE', '20', 10);
            """
        )

    async def first(self, statement, params=()):
        row = self.db.execute(statement, params).fetchone()
        return dict(row) if row is not None else None

    async def run(self, statement, params=()):
        self.db.execute(statement, params)
        self.db.commit()

    async def create_source_document(self, **kwargs):
        external_id = kwargs["external_id"]
        existing = self.db.execute(
            "SELECT id FROM source_documents WHERE external_id=?", (external_id,)
        ).fetchone()
        if existing:
            return int(existing["id"])
        cursor = self.db.execute(
            "INSERT INTO source_documents(external_id,title,published_at) VALUES(?,?,?)",
            (external_id, kwargs["title"], kwargs["published_at"]),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def current_cap(self):
        return self.db.execute(
            "SELECT max_price_nok FROM buyback_programs WHERE id=1"
        ).fetchone()["max_price_nok"]

    def cap_as_of(self, day):
        row = self.db.execute(
            """
            SELECT max_price_nok FROM buyback_program_cap_history
            WHERE program_id=1 AND substr(effective_at,1,10)<=?
            ORDER BY effective_at DESC, id DESC LIMIT 1
            """,
            (day,),
        ).fetchone()
        return row["max_price_nok"] if row else None


def announcement(
    body="The maximum consideration to be paid for shares acquired under "
    "the buyback program has been increased from NOK 20 per share to NOK 30 per share.",
):
    return NewsWebMessage(
        message_id=684999,
        news_id=None,
        title="Share Buyback Program - update",
        body=body,
        issuer_id=7759,
        issuer_sign="OTEC",
        issuer_name="Otello Corporation ASA",
        published_at="2026-10-21T06:00:00Z",
        markets=(),
        category_ids=(),
        attachments=(),
        corrected_by_message_id=0,
        correction_for_message_id=0,
        client_announcement_id=None,
    )


class ParseCapTest(unittest.TestCase):
    def test_title_routes_amendment_not_weekly_status(self):
        self.assertTrue(is_program_update_title("Share Buyback Program - update"))
        self.assertTrue(is_program_update_title("Share Buyback Program amendment"))
        self.assertFalse(is_program_update_title("Otello Corporation share buyback program status"))

    def test_read_new_instead_of_old_cap(self):
        self.assertEqual(parse_amended_price_cap(announcement().body), Decimal("30"))
        self.assertEqual(
            parse_amended_price_cap("Maximum price per share has been raised from NOK 20 to NOK 25."),
            Decimal("25"),
        )
        self.assertEqual(
            parse_amended_price_cap("Maximum consideration under the share buyback program is NOK 25.50 per share."),
            Decimal("25.50"),
        )

    def test_ambiguous_news_is_not_guessed(self):
        with self.assertRaisesRegex(ValueError, "mangler entydig"):
            parse_amended_price_cap("The repurchase program was updated. NOK 30 million authorised.")


class BuybackCapHistoryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = SQLiteRepository()

    async def test_amendment_updates_live_cap_and_keeps_original(self):
        outcome = await ingest_program_cap_amendment(self.repo, announcement())
        self.assertTrue(outcome["applied_as_latest"])
        self.assertEqual(self.repo.current_cap(), "30")
        self.assertEqual(self.repo.cap_as_of("2026-10-20"), "20")
        self.assertEqual(self.repo.cap_as_of("2026-10-21"), "30")
        self.assertEqual(
            self.repo.db.execute(
                "SELECT COUNT(*) AS n FROM buyback_program_cap_history"
            ).fetchone()["n"],
            2,
        )

    async def test_older_weekly_statement_does_not_restore_old_limit(self):
        await ingest_program_cap_amendment(self.repo, announcement())
        program = await self.repo.first("SELECT * FROM buyback_programs WHERE id=1")
        outcome = await record_program_price_cap(
            self.repo,
            program=program,
            source_document_id=21,
            max_price_nok=Decimal("20"),
            effective_at="2026-10-18T17:38:10Z",
            event_kind="STATUS",
        )
        self.assertFalse(outcome["applied_as_latest"])
        self.assertEqual(self.repo.current_cap(), "30")
        self.assertEqual(self.repo.cap_as_of("2026-10-20"), "20")

    async def test_repeated_amendment_is_idempotent(self):
        first = await ingest_program_cap_amendment(self.repo, announcement())
        second = await ingest_program_cap_amendment(self.repo, announcement())
        self.assertEqual(first["new_price_cap_nok"], second["new_price_cap_nok"])
        self.assertEqual(
            self.repo.db.execute(
                "SELECT COUNT(*) AS n FROM buyback_program_cap_history"
            ).fetchone()["n"],
            2,
        )

    async def test_missing_cap_reports_review_error(self):
        with self.assertRaisesRegex(ValueError, "mangler entydig"):
            await ingest_program_cap_amendment(
                self.repo, announcement("The buyback program is extended.")
            )
        self.assertEqual(self.repo.current_cap(), "20")


if __name__ == "__main__":
    unittest.main()
