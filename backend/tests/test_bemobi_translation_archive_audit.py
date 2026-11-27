import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_bemobi_translation_archive import COUNTS, DETAIL, VERSIONS, report


def test_inventory_does_not_confuse_superseded_versions_and_unqueued(capsys):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE sources(id INTEGER, code TEXT);
    INSERT INTO sources VALUES(1,'CVM'),(2,'BEMOBI_IR'),(3,'OTHER');
    CREATE TABLE source_documents(id INTEGER, source_id INTEGER, published_at TEXT,
      translation_status TEXT, document_type TEXT, url TEXT, metadata_json TEXT,
      translation_attempts INTEGER, translated_pdf_key TEXT, norwegian_summary TEXT);
    INSERT INTO source_documents VALUES
      (1,1,'2021-01-01',NULL,'CVM_IPE_METADATA','https://secret.example/a','{"is_latest_version":true}',0,NULL,NULL),
      (2,1,'2021-02-01',NULL,'CVM_IPE_METADATA','https://secret.example/b','{"is_latest_version":false}',0,NULL,NULL),
      (3,1,'2021-03-01','READY','CVM_IPE_METADATA','https://secret.example/c','{}',1,'key','private'),
      (4,1,'2021-04-01','FAILED','CVM_IPE_METADATA','https://secret.example/d','invalid',3,NULL,NULL),
      (5,2,'2020-01-01','NOT_REQUIRED','IR_HTML','https://secret.example/e','{}',0,NULL,NULL),
      (6,3,'2020-01-01','FAILED','OTHER','https://secret.example/f','{}',3,NULL,NULL),
      (7,2,NULL,'READY','IR_PDF','https://secret.example/g','{}',1,NULL,NULL);
    """)
    before = db.total_changes
    rows = [dict(r) for r in db.execute(COUNTS)]
    cvm = next(r for r in rows if r["source"] == "CVM")
    assert cvm["total"] == 4 and cvm["unqueued"] == 2 and cvm["exhausted"] == 1
    unknown = next(r for r in rows if r["year"] == "UNKNOWN")
    assert unknown["ready_without_pdf"] == unknown["ready_without_summary"] == 1
    detail = [dict(r) for r in db.execute(DETAIL)]
    assert any(r["version"] == "LATEST" and r["status"] == "UNQUEUED" for r in detail)
    assert any(r["version"] == "SUPERSEDED" and r["status"] == "UNQUEUED" for r in detail)
    assert sum(r["total"] for r in db.execute(VERSIONS)) == 6
    report(lambda sql, params: {"results": [dict(r) for r in db.execute(sql, params)]})
    assert "secret.example" not in capsys.readouterr().out
    assert db.total_changes == before
