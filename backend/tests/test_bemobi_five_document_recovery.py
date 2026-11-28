from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from reactivate_bemobi_five_documents import (
    CUTOFF, EXPECTED, SELECT_SQL, UPDATE_SQL, eligible, fingerprint, reactivate_one,
)


def row():
    return dict(document_id=7538, url="https://example.invalid/7538",
                delivery="2026-11-12", status="FAILED", attempts=3,
                processed_at="2026-11-28T10:59:00.000Z",
                error="translation:ValueError: Dokumentet overskrider sikker behandlingsgrense")


@pytest.mark.parametrize("change", [
    {"document_id": 7540}, {"status": "READY"}, {"status": "PROCESSING"},
    {"status": "PENDING"}, {"attempts": 2}, {"delivery": "2026-11-13"},
    {"processed_at": "2026-11-28T11:03:00.000Z"}, {"processed_at": None},
    {"error": "download: HTTP 526"},
])
def test_eligibility(change):
    assert eligible(row())
    assert not eligible({**row(), **change})
    assert len(EXPECTED) == 5


def test_compare_and_set():
    original = row()
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE sources(id INTEGER, code TEXT);
    INSERT INTO sources VALUES(1, 'CVM');
    CREATE TABLE source_documents(id INTEGER, source_id INTEGER, url TEXT, published_at TEXT,
      translation_status TEXT, translation_attempts INTEGER, translation_processed_at TEXT,
      translation_error TEXT, extraction_status TEXT, summary_status TEXT);
    """)
    db.execute("INSERT INTO source_documents VALUES(?,1,?,?,?,?,?,?, 'FAILED','FAILED')",
               (original["document_id"], original["url"], original["delivery"], original["status"],
                original["attempts"], original["processed_at"], original["error"]))

    def query(sql, params):
        cur = db.execute(sql, params)
        if sql == SELECT_SQL:
            return {"results": [dict(r) for r in cur.fetchall()]}
        assert sql == UPDATE_SQL
        return {"meta": {"changes": cur.rowcount}}

    item = {"document_id": 7538, "fingerprint": fingerprint(original)}
    assert reactivate_one({**item, "fingerprint": "wrong"}, query) == 0
    assert reactivate_one(item, query) == 1
    assert reactivate_one(item, query) == 0
    actual = query(SELECT_SQL, (7538,))["results"][0]
    assert actual["status"] == "PENDING"
    assert actual["attempts"] == 0
    assert actual["error"] is None


def test_concurrent_error_change_prevents_reset():
    original = row()
    calls = []

    def query(sql, params):
        calls.append(sql)
        if sql == SELECT_SQL:
            return {"results": [{**original, "error": original["error"] + " changed"}]}
        raise AssertionError("Ingen skriving ved endret rad")

    assert reactivate_one({"document_id": 7538, "fingerprint": fingerprint(original)}, query) == 0
    assert calls == [SELECT_SQL]


def test_completed_incident_recovery_is_manual_only():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/bemobi-five-document-recovery.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "  workflow_dispatch:" in triggers
    assert "  pull_request:" in triggers
    assert "  push:" not in triggers
    assert "  schedule:" not in triggers
    assert "github.ref == 'refs/heads/main' && github.event_name == 'workflow_dispatch'" in workflow
