import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
from backfill_bemobi_translation_history import COUNTS, BUFFER, SELECT, UPDATE, DEFER


def test_rolling_scope_and_compare_and_set():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE sources(id INTEGER,code TEXT);
    INSERT INTO sources VALUES(1,'CVM'),(2,'BEMOBI_IR');
    CREATE TABLE source_documents(id INTEGER,source_id INTEGER,document_type TEXT,url TEXT,
       published_at TEXT,metadata_json TEXT,translation_status TEXT,translation_attempts INTEGER,
       extraction_status TEXT,summary_status TEXT);
    INSERT INTO source_documents VALUES
      (1,1,'CVM_IPE_METADATA','u1',date('now','-24 months'),'{"is_latest_version":true}',NULL,0,NULL,NULL),
      (2,1,'CVM_IPE_METADATA','u2',date('now','-24 months','-1 day'),'{"is_latest_version":true}',NULL,0,NULL,NULL),
      (3,1,'CVM_IPE_METADATA','u3',date('now'),'{"is_latest_version":false}',NULL,0,NULL,NULL),
      (4,1,'CVM_IPE_METADATA','u4',date('now'),'{"is_latest_version":true}','READY',1,NULL,NULL),
      (5,2,'CVM_IPE_METADATA','u5',date('now'),'{"is_latest_version":true}',NULL,0,NULL,NULL),
      (6,1,'CVM_IPE_METADATA','u6',date('now'),'{"is_latest_version":true}',NULL,0,NULL,NULL),
      (7,1,'CVM_IPE_METADATA','u7',date('now'),'invalid',NULL,0,NULL,NULL),
      (8,1,'CVM_IPE_METADATA','u8',date('now'),'{"is_latest_version":true}','FAILED',3,NULL,NULL),
      (9,1,'CVM_IPE_METADATA','u9',date('now','+1 day'),'{"is_latest_version":true}',NULL,0,NULL,NULL),
      (10,1,'CVM_IPE_METADATA','u10',date('now'),'{"is_latest_version":true}',NULL,0,NULL,NULL);
    """)
    rows = [dict(r) for r in db.execute(SELECT,(6,))]
    assert [r["document_id"] for r in rows] == [10,6,1]
    assert sum(r["candidates"] for r in db.execute(COUNTS)) == 3
    assert db.execute(BUFFER).fetchone()["staged"] == 0
    r=rows[0]
    params=(r["document_id"],r["url"],r["delivery"])
    assert db.execute(UPDATE,params).rowcount==1
    assert db.execute(UPDATE,params).rowcount==0
    assert db.execute(BUFFER).fetchone()["staged"]==1
    r=rows[1]
    params=(r["document_id"],r["url"],r["delivery"])
    assert db.execute(DEFER,params).rowcount==1
    assert [r["document_id"] for r in db.execute(SELECT,(6,))]==[1]
    assert db.execute("SELECT translation_status FROM source_documents WHERE id=6").fetchone()[0] is None
    db.close()
