"""Verify the bounded first page against the original joined news query."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from news_events import NEWS_FIRST_PAGE_QUERY, NEWS_PAGE_QUERY


def test_first_page_matches_original_and_reduces_history_work():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript("""
        CREATE TABLE instruments(id INTEGER PRIMARY KEY,symbol TEXT UNIQUE);
        CREATE TABLE sources(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name TEXT);
        CREATE TABLE source_documents(
            id INTEGER PRIMARY KEY,source_id INTEGER,published_at TEXT,url TEXT,
            metadata_json TEXT,content_sha256 TEXT,translation_status TEXT,
            summary_status TEXT,norwegian_title TEXT,norwegian_summary TEXT,
            translated_pdf_key TEXT
        );
        CREATE TABLE company_news(
            id INTEGER PRIMARY KEY,issuer_instrument_id INTEGER,
            source_document_id INTEGER UNIQUE,published_at TEXT,headline TEXT,
            category TEXT,nav_impact TEXT,processing_status TEXT,summary TEXT
        );
        CREATE INDEX idx_company_news_issuer_time ON company_news(issuer_instrument_id,published_at);
        INSERT INTO instruments VALUES(1,'OTEC'),(2,'BMOB3'),(3,'LIF');
        INSERT INTO sources VALUES(1,'NEWSWEB','NewsWeb'),(2,'CVM','CVM'),
            (3,'BEMOBI_IR','Bemobi IR'),(4,'OTHER','Other');
        """)
        for i in range(1,6001):
            day = (date(2018,1,1)+timedelta(days=i//3)).isoformat()
            db.execute(
                "INSERT INTO source_documents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (i,1+i%4,day if i%101 else None,f"https://example.test/{i}",
                 '{"is_latest_version":false}' if i%7==0 else '{}',
                 str(i), "READY", "READY", "Norsk tittel", "Norsk sammendrag", f"pdf/{i}"),
            )
            db.execute(
                "INSERT INTO company_news VALUES(?,?,?,?,?,?,?,?,?)",
                (i,1+i%3,i,day if i%47 else None,"Original","OTHER","NONE","PARSED","Summary"),
            )

        # Exact ties, both publication fields NULL, and newer document fallback.
        db.execute("UPDATE company_news SET published_at=NULL WHERE id IN (5998,5999,6000)")
        db.execute("UPDATE source_documents SET published_at='2027-01-01' WHERE id IN (5998,5999)")
        db.execute("UPDATE source_documents SET published_at=NULL WHERE id=6000")

        def execute(sql, params):
            steps = 0

            def count():
                nonlocal steps
                steps += 1
                return 0

            db.set_progress_handler(count, 1)
            try:
                return [dict(row) for row in db.execute(sql,params)],steps
            finally:
                db.set_progress_handler(None,0)

        for limit in (1,3,180,300,6001):
            expected,before = execute(NEWS_PAGE_QUERY,(limit,0))
            actual,after = execute(NEWS_FIRST_PAGE_QUERY,(limit,0))
            assert actual == expected
            if limit == 180:
                assert after < before, (before,after)

        # Compare every selected field, including fallback dates and translation
        # metadata; retain original SQL for later pages.
        full,_ = execute(NEWS_PAGE_QUERY,(6001,0))
        assert full
        assert any(row["published_at"] is None for row in full)
        assert any(row["published_at"] == "2027-01-01" for row in full)
        assert all(row["symbol"] in ("OTEC","BMOB3") for row in full)
        assert all(row["source_code"] in ("NEWSWEB","CVM","BEMOBI_IR") for row in full)
        plan = " ".join(str(tuple(row)) for row in db.execute(
            "EXPLAIN QUERY PLAN "+NEWS_FIRST_PAGE_QUERY,(180,0)
        ))
        assert "idx_company_news_issuer_time" in plan

        db.execute("DELETE FROM instruments")
        assert execute(NEWS_FIRST_PAGE_QUERY,(180,0))[0] == []
    finally:
        db.close()
