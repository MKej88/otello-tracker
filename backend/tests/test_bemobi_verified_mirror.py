"""Fail-closed integrity tests for the pinned official CVM R2 mirror."""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
import bemobi_verified_mirror as mirror  # noqa: E402


class Stored:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.size = len(payload)

    async def arrayBuffer(self):
        return self.payload


class Bucket:
    def __init__(self, payload=None):
        self.payload = payload
        self.keys = []

    async def get(self, key):
        self.keys.append(key)
        return None if self.payload is None else Stored(self.payload)


def _pin_test_document(monkeypatch, kind="jcp"):
    original = mirror.PINNED_Q3_DOCUMENTS[kind]
    payload = b"%PDF-1.6\nvalidated test fixture\n%%EOF\n"
    test_spec = {
        **original,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "max_bytes": 1024,
    }
    monkeypatch.setitem(mirror.PINNED_Q3_DOCUMENTS, kind, test_spec)
    return payload, test_spec


def test_verified_mirror_reads_exact_pinned_object(monkeypatch):
    payload, spec = _pin_test_document(monkeypatch)
    bucket = Bucket(payload)
    result, url = asyncio.run(mirror.read_verified_q3_document(bucket, "jcp"))
    assert result == payload
    assert url == spec["url"]
    assert bucket.keys == [spec["key"]]


@pytest.mark.parametrize("variant", ["wrong_sha", "wrong_size", "wrong_magic", "missing"])
def test_verified_mirror_rejects_nonmatching_or_missing_objects(monkeypatch, variant):
    payload, _ = _pin_test_document(monkeypatch)
    bucket = Bucket(payload)
    if variant == "wrong_sha":
        bucket.payload = payload.replace(b"validated", b"tampered!")
    elif variant == "wrong_size":
        bucket.payload = payload + b"x"
    elif variant == "wrong_magic":
        bucket.payload = b"NO_PDF" + payload[6:]
    elif variant == "missing":
        bucket.payload = None
    with pytest.raises((RuntimeError, ValueError)):
        asyncio.run(mirror.read_verified_q3_document(bucket, "jcp"))


def test_missing_bucket_or_unknown_kind_is_never_accepted():
    with pytest.raises(RuntimeError, match="no private R2 bucket"):
        asyncio.run(mirror.read_verified_q3_document(None, "jcp"))
    with pytest.raises(ValueError, match="Unknown pinned"):
        asyncio.run(mirror.read_verified_q3_document(Bucket(), "other"))
