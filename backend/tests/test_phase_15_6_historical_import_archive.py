from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from historical_import_archive import archive_historical_import  # noqa: E402


class _Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, payload: bytes):
        self.objects[key] = bytes(payload)
        return {"key": key}


def test_historical_import_archives_exact_bytes_and_manifest() -> None:
    bucket = _Bucket()
    payload = b"Date,Price\n2026-08-17,17.50\n"
    result = asyncio.run(
        archive_historical_import(
            bucket,
            payload,
            source_code="INVESTING",
            filename="Otello Corporation ASA Stock Price History.csv",
            logical_date="2026-08-17",
            import_purpose="OTEC historical close backfill",
        )
    )
    assert result["status"] == "ok"
    assert bucket.objects[result["r2_key"]] == payload
    manifest = json.loads(bucket.objects[result["manifest_r2_key"]])
    assert manifest["source_code"] == "INVESTING"
    assert manifest["content_sha256"] == result["content_sha256"]
    assert manifest["import_purpose"] == "OTEC historical close backfill"
