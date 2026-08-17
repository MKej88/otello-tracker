from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from newsweb_fast_refresh import _existing_newsweb_documents  # noqa: E402


class _Repository:
    async def all(self, sql, parameters=()):
        assert "sd.published_at >= ?" in sql
        assert parameters == ("2026-08-01T00:00:00Z",)
        return [
            {
                "external_id": "newsweb-message:123",
                "metadata_json": json.dumps({"archive_category": "RESULTS"}),
                "fetched_at": "2026-08-16T08:00:00Z",
            },
            {
                "external_id": "newsweb-message:123#sha256:abc",
                "metadata_json": json.dumps(
                    {
                        "archive_category": "RESULTS",
                        "logical_external_id": "newsweb-message:123",
                        "content_version_sha256": "abcdef",
                    }
                ),
                "fetched_at": "2026-08-17T07:30:00Z",
            },
        ]


def test_newsweb_dedupe_uses_latest_immutable_content_version() -> None:
    existing = asyncio.run(
        _existing_newsweb_documents(_Repository(), from_date="2026-08-01")
    )

    assert list(existing) == ["newsweb-message:123"]
    assert existing["newsweb-message:123"]["_fetched_at"] == "2026-08-17T07:30:00Z"
    assert existing["newsweb-message:123"]["content_version_sha256"] == "abcdef"
