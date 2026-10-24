import asyncio
import gzip
import hashlib
import json
import unittest
from r2_snapshot import SNAPSHOT_VERSION, _canonical_json, verify_snapshot_readback


class FakeObject:
    def __init__(self, raw):
        self.raw = raw

    async def text(self):
        return self.raw.decode("utf-8")

    async def arrayBuffer(self):
        return self.raw


class FakeBucket:
    def __init__(self, objects):
        self.objects = objects

    async def get(self, key):
        raw = self.objects.get(key)
        return FakeObject(raw) if raw is not None else None


def fixture():
    day, table = "2026-10-24", "sources"
    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "target_date": day, "table": table, "order_by": "id",
        "chunk_index": 0, "rows": [{"id": 1, "code": "NORGES_BANK"}],
    }
    raw = _canonical_json(payload)
    compressed = gzip.compress(raw, mtime=0)
    digest = hashlib.sha256(raw).hexdigest()
    key = f"snapshots/d1/{day}/{table}/part-00000-{digest[:20]}.json.gz"
    entry = {
        "table": table, "chunk_index": 0, "row_count": 1,
        "first_key": 1, "last_key": 1, "key": key,
        "logical_sha256": digest,
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
    }
    logical = {
        "snapshot_version": SNAPSHOT_VERSION,
        "target_date": day,
        "tables": [table],
        "row_counts": {table: 1},
        "chunks": [{
            "table": table, "chunk_index": 0,
            "logical_sha256": digest, "row_count": 1,
        }],
    }
    digest_manifest = hashlib.sha256(_canonical_json(logical)).hexdigest()
    manifest_key = f"snapshots/d1/{day}/manifest-{digest_manifest[:20]}.json"
    manifest = {
        **logical, "logical_sha256": digest_manifest,
        "table_count": 1, "chunk_count": 1, "chunk_objects": [entry],
    }
    summary = {"target_date": day, "logical_sha256": digest_manifest,
               "chunk_count": 1, "manifest_key": manifest_key}
    return FakeBucket({manifest_key: _canonical_json(manifest), key: compressed}), summary, key


class ReadbackTests(unittest.TestCase):
    def test_readback_ok(self):
        bucket, summary, _ = fixture()
        r = asyncio.run(verify_snapshot_readback(bucket, summary))
        self.assertEqual(r["readback_status"], "ok")
        self.assertEqual(r["checked_chunks"], 1)

    def test_missing_chunk_fails(self):
        bucket, summary, key = fixture()
        del bucket.objects[key]
        with self.assertRaisesRegex(ValueError, "missing"):
            asyncio.run(verify_snapshot_readback(bucket, summary))

    def test_corrupt_chunk_fails(self):
        bucket, summary, key = fixture()
        bucket.objects[key] += b"x"
        with self.assertRaisesRegex(ValueError, "compressed digest"):
            asyncio.run(verify_snapshot_readback(bucket, summary))

    def test_missing_manifest_fails(self):
        bucket, summary, _ = fixture()
        del bucket.objects[summary["manifest_key"]]
        with self.assertRaisesRegex(ValueError, "manifest"):
            asyncio.run(verify_snapshot_readback(bucket, summary))


if __name__ == "__main__":
    unittest.main()
