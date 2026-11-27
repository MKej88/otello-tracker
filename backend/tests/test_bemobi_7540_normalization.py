import asyncio
import io
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from test_bemobi_translation_mirror import fixture, IDENTITY, DELIVERY
from bemobi_7540_normalization import (normalize_padding, verify_pair, make_manifest,
    validate_normalization_manifest, verify_manifest_pair, read_7540_normalization,
    manifest_key_7540)
from bemobi_translation_mirror import official_urls, verify_pdf
from bemobi_document_translation import _download_original
from recover_bemobi_cvm_7540 import SELECT, UPDATE, CUTOFF


def sample_pdf():
    # Use the production PDF renderer to provide real nonempty page text.
    from bemobi_document_translation import render_norwegian_pdf
    return render_norwegian_pdf("Tittel", DELIVERY, "A companhia tem 123 ações.")


def test_padding_only_and_regular_gate_unchanged():
    core = sample_pdf()
    raw = core + b"\n" + b"\0" * 96140
    normalized = normalize_padding(raw)
    assert normalized == core[:core.rfind(b"%%EOF")+5] + b"\n"
    assert verify_pair(raw, normalized)[0] == 1
    for bad in (raw + b"arbitrary text", raw + b"<html>", core, b"not PDF" + raw,
                core + b"\0" * (128 * 1024 + 1)):
        with pytest.raises(ValueError):
            normalize_padding(bad)
    with pytest.raises(ValueError):
        normalize_padding(core.replace(b"%%EOF", b"/ByteRange [0 1 2 3]\n%%EOF") + b"\0" * 96140)
    import hashlib
    with pytest.raises(ValueError):
        verify_pdf(raw, {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})


def test_pair_manifest_and_runtime_only_for_exact_id():
    raw = sample_pdf() + b"\0" * 96140
    normalized = normalize_padding(raw)
    manifest = make_manifest(IDENTITY, DELIVERY, fixture()["listing"], raw, normalized)
    validate_normalization_manifest(manifest, IDENTITY, DELIVERY, 7540)
    assert verify_manifest_pair(manifest, raw, normalized) == normalized
    for wrong in (7541, None):
        with pytest.raises(ValueError):
            validate_normalization_manifest(manifest, IDENTITY, DELIVERY, wrong)
    with pytest.raises(ValueError):
        verify_manifest_pair(manifest, raw + b"\0", normalized)
    with pytest.raises(ValueError):
        verify_manifest_pair(manifest, raw, normalized + b" ")
    class Bucket:
        async def get(self, key):
            data = {manifest_key_7540(IDENTITY): json.dumps(manifest).encode(),
                    manifest["original"]["key"]: raw, manifest["processing"]["key"]: normalized}.get(key)
            if data is None:
                return None
            async def read():
                return data
            return SimpleNamespace(size=len(data), arrayBuffer=read)
    url = official_urls(IDENTITY)[0]
    assert asyncio.run(read_7540_normalization(Bucket(), url, delivery=DELIVERY, document_id=7540)) == normalized
    async def forbidden(*args, **kwargs):
        raise AssertionError("Direct transport must not be used for 7540")
    trace = {"downloads": []}
    assert asyncio.run(_download_original(url, Bucket(), forbidden, trace=trace,
                                          delivery=DELIVERY, document_id=7540)) == normalized
    assert trace["downloads"] == [{"route": "normalized_r2", "result": "ok"}]


def test_recovery_is_targeted_and_idempotent():
    db = sqlite3.connect(":memory:")
    db.executescript("""
    CREATE TABLE sources(id INTEGER,code TEXT);
    INSERT INTO sources VALUES(1,'CVM');
    CREATE TABLE source_documents(id INTEGER,source_id INTEGER,url TEXT,published_at TEXT,
      translation_status TEXT,translation_attempts INTEGER,translation_error TEXT,
      translation_processed_at TEXT,extraction_status TEXT,summary_status TEXT);
    INSERT INTO source_documents VALUES(7540,1,'url','2026-11-12','FAILED',3,
      'download:RuntimeError: originaldokument HTTP 526','2026-11-27T14:00:00.000Z','FAILED','FAILED');
    INSERT INTO source_documents SELECT 7541,source_id,url,published_at,translation_status,
      translation_attempts,translation_error,translation_processed_at,extraction_status,summary_status
      FROM source_documents WHERE id=7540;
    """)
    assert len(db.execute(SELECT,(7540,CUTOFF)).fetchall()) == 1
    params = (7540,"url",DELIVERY,"2026-11-27T14:00:00.000Z",CUTOFF)
    assert db.execute(UPDATE,params).rowcount == 1
    assert db.execute(UPDATE,params).rowcount == 0
    assert db.execute("SELECT translation_status FROM source_documents WHERE id=7541").fetchone()[0] == "FAILED"
    db.close()
