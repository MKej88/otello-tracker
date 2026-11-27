"""Offline, fail-closed regression tests for the incident-specific recovery."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from reactivate_bemobi_translation_documents import (
    VERIFIED_IDS, INVESTIGATE_ID, CUTOFF, UPDATE_SQL, eligible, recover_rows,
)
from test_bemobi_translation_mirror import fixture, RAW, IDENTITY, DELIVERY
from bemobi_translation_mirror import manifest_key


def row(document_id=4059, **overrides):
    manifest = fixture()
    data = dict(document_id=document_id, url=manifest["artifact"]["url"], delivery=DELIVERY,
                status="FAILED", attempts=3, processed_at="2026-11-27T14:00:00.000Z", has_error=1)
    data.update(overrides)
    return data


def test_only_incident_ids_and_old_unresolved_attempts():
    assert len(VERIFIED_IDS) == 9
    assert eligible(row())
    assert eligible(row(processed_at=None, attempts=0))
    for bad in (row(INVESTIGATE_ID), row(999), row(status="READY"), row(status="PROCESSING"),
                row(has_error=0), row(processed_at="2026-11-27T14:36:00.000Z")):
        assert not eligible(bad)


def test_verified_mirror_required_and_concurrent_updates_are_safe(tmp_path):
    manifest = fixture()
    objects = {manifest_key(IDENTITY): json.dumps(manifest).encode(),
               manifest["artifact"]["key"]: RAW}

    def download(key, path):
        path.write_bytes(objects[key])

    updates = []
    def query(sql, params):
        updates.append((sql, params))
        return {"meta": {"changes": 1}}

    assert recover_rows([row(), row(INVESTIGATE_ID), row(4060, status="READY")],
                        tmp_path, download, query) == (1, 1, 0)
    assert len(updates) == 1 and updates[0][1][0] == 4059
    objects[manifest["artifact"]["key"]] = b"corrupt"
    assert recover_rows([row(4062)], tmp_path, download, query) == (0, 0, 1)
    assert len(updates) == 1


def test_compare_and_set_is_idempotent_and_does_not_reset_newer_attempts():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE sources(id INTEGER, code TEXT);
        INSERT INTO sources VALUES (1,'CVM');
        CREATE TABLE source_documents(id INTEGER, url TEXT, published_at TEXT, source_id INTEGER,
          translation_status TEXT, translation_attempts INTEGER, translation_error TEXT,
          translation_processed_at TEXT, extraction_status TEXT, summary_status TEXT);
    """)
    old = row()
    db.execute("INSERT INTO source_documents VALUES (?,?,?,?,?,?,?,?,?,?)",
               (4059, old["url"], DELIVERY, 1, "FAILED", 3, "HTTP 526",
                old["processed_at"], "FAILED", "FAILED"))
    params = (4059, old["url"], DELIVERY, "FAILED", 3, old["processed_at"], CUTOFF)
    assert db.execute(UPDATE_SQL, params).rowcount == 1
    assert db.execute(UPDATE_SQL, params).rowcount == 0
    assert db.execute("SELECT translation_status,translation_attempts,translation_error FROM source_documents").fetchone() == ("PENDING",0,None)
    db.execute("UPDATE source_documents SET translation_status='FAILED',translation_attempts=1,translation_error='new',translation_processed_at='2026-11-27T14:36:00.000Z'")
    assert db.execute(UPDATE_SQL, (4059, old["url"], DELIVERY, "FAILED",1,"2026-11-27T14:36:00.000Z",CUTOFF)).rowcount == 0
    db.close()
