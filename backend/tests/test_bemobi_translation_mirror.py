"""Offline tests for exact filing provenance and private translation PDF fallback."""
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloudflare" / "src"))
from bemobi_translation_mirror import (manifest_key, pdf_key, official_urls,
                                       validate_manifest, read_translation_mirror)
from bemobi_document_translation import _download_original
from bemobi_cvm_rad import filing_identity

IDENTITY = ("123", "456", "1")
DELIVERY = "2026-11-12"
RAW = b"%PDF-1.4 test\n%%EOF"


def fixture():
    fields = ["BEMOBI MOBILE TECH S.A.", "025500", "Comunicado",
              "Aviso", "Documento", "12/11/2026", "12/11/2026", "Ativo",
              "", "EN", "OpenDownloadDocumentos('456','1','123','IPE')", "Documento"]
    listing = {"d": {"temErro": False, "dados": "$&".join(fields)}}
    digest = hashlib.sha256(RAW).hexdigest()
    return dict(schema=1, cvm_code="25500", identity=list(IDENTITY), delivery=DELIVERY,
                listing=listing, artifact=dict(url=official_urls(IDENTITY)[0],
                sha256=digest, bytes=len(RAW), key=pdf_key(IDENTITY, digest)))


class Bucket:
    def __init__(self, manifest, raw=RAW):
        self.objects = {manifest_key(IDENTITY): json.dumps(manifest).encode(),
                        manifest["artifact"]["key"]: raw}

    async def get(self, key):
        raw = self.objects.get(key)
        if raw is None:
            return None
        async def read():
            return raw
        return SimpleNamespace(size=len(raw), arrayBuffer=read)


def test_exact_version_and_integrity():
    manifest = fixture()
    for url in official_urls(IDENTITY):
        assert filing_identity(url) == IDENTITY
        assert asyncio.run(read_translation_mirror(Bucket(manifest), url, delivery=DELIVERY)) == RAW
    with pytest.raises(ValueError):
        asyncio.run(read_translation_mirror(Bucket(manifest, b"%PDF-tampered"),
                                            official_urls(IDENTITY)[0]))
    with pytest.raises(ValueError):
        asyncio.run(read_translation_mirror(Bucket(manifest), official_urls(IDENTITY)[0],
                                            delivery="2026-11-13"))
    with pytest.raises(ValueError):
        validate_manifest(manifest, ("123", "456", "2"))


def test_wrong_issuer_and_inactive_filing_rejected():
    for original, replacement in (("BEMOBI MOBILE TECH S.A.$&025500", "OTHER$&999"),
                                  ("$&Ativo$&", "$&Inativo$&")):
        manifest = fixture()
        manifest["listing"]["d"]["dados"] = manifest["listing"]["d"]["dados"].replace(original, replacement)
        with pytest.raises(ValueError):
            validate_manifest(manifest, IDENTITY)


def test_worker_uses_r2_only_after_both_official_routes_fail():
    async def fetcher(*args, **kwargs):
        return SimpleNamespace(ok=False, status=526)
    trace = {"downloads": []}
    result = asyncio.run(_download_original(official_urls(IDENTITY)[0], Bucket(fixture()),
                                           fetcher, trace=trace, delivery=DELIVERY))
    assert result == RAW
    assert trace["downloads"] == [
        {"route": "original", "result": "http_error", "http": 526},
        {"route": "official_alternative", "result": "http_error", "http": 526},
        {"route": "queue_r2", "result": "ok"},
    ]
    with pytest.raises(RuntimeError, match="526"):
        asyncio.run(_download_original(official_urls(IDENTITY)[0], Bucket(fixture(), b"bad"), fetcher))


def test_workflow_separates_credentials_and_does_not_write_d1():
    workflow = (ROOT / ".github/workflows/bemobi-translation-r2-mirror.yml").read_text()
    script = (ROOT / "tools/mirror_bemobi_translation_queue.py").read_text()
    assert "CLOUDFLARE_READ_TOKEN" in workflow
    assert "build" in workflow
    assert "pull_request" in workflow
    assert "SELECT sd.id" in script
    assert "UPDATE source_documents" not in script
    assert "INSERT INTO" not in script
    assert "NoRedirect" in script


@pytest.mark.parametrize("existing,read_error,expected,writes", [
    (RAW, False, "reused", 0),
    (b"corrupt", False, "written", 1),
    (None, False, "written", 1),
    (RAW, True, "written", 1),
])
def test_verified_object_reuses_only_exact_bytes(tmp_path, monkeypatch, existing, read_error, expected, writes):
    sys.path.insert(0, str(ROOT / "tools"))
    from mirror_bemobi_translation_queue import publish_verified_object
    import subprocess

    local = tmp_path / "original.pdf"
    readback = tmp_path / "readback.pdf"
    local.write_bytes(RAW)
    # A stale local readback must not masquerade as a successful remote read.
    readback.write_bytes(RAW)
    remote = existing
    calls = []

    def run(command, **kwargs):
        nonlocal remote
        operation = command[3]
        calls.append(operation)
        target = Path(next(value[7:] for value in command if value.startswith("--file=")))
        if operation == "put":
            remote = target.read_bytes()
            return SimpleNamespace(returncode=0)
        if remote is None or (read_error and len(calls) == 1):
            return SimpleNamespace(returncode=1)
        target.write_bytes(remote)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert publish_verified_object("wrangler", "bucket/object", local, readback,
                                   "application/pdf", reuse=True) == expected
    assert calls.count("put") == writes
    assert readback.read_bytes() == RAW
    assert calls[-1] == "get"


def test_manifest_still_written_and_verified_and_bad_readback_fails(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    from mirror_bemobi_translation_queue import publish_verified_object
    import subprocess

    local = tmp_path / "manifest.json"
    readback = tmp_path / "readback.json"
    local.write_bytes(b"manifest")
    calls = []

    def run(command, **kwargs):
        operation = command[3]
        calls.append(operation)
        if operation == "get":
            readback.write_bytes(b"bad")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="R2-tilbakelesing avviker"):
        publish_verified_object("wrangler", "bucket/manifest", local, readback, "application/json")
    assert calls == ["put", "get"]
