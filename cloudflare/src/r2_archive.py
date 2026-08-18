from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe(value: str, *, fallback: str = "item") -> str:
    cleaned = _SAFE_RE.sub("-", value.strip()).strip("-._")
    return cleaned[:120] or fallback


def content_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def raw_object_key(
    *,
    source: str,
    kind: str,
    logical_date: str,
    digest: str,
    filename: str,
) -> str:
    source_part = _safe(source.lower(), fallback="source")
    kind_part = _safe(kind.lower(), fallback="raw")
    date_part = _safe(logical_date, fallback="undated")
    name_part = _safe(filename, fallback="payload.bin")
    return f"raw/{source_part}/{kind_part}/{date_part}/{digest[:20]}-{name_part}"


async def archive_bytes(
    bucket: Any,
    payload: bytes,
    *,
    source: str,
    kind: str,
    logical_date: str,
    filename: str,
) -> dict[str, Any]:
    if not payload:
        raise ValueError("R2-arkiv nekter tom payload")
    digest = content_sha256(payload)
    key = raw_object_key(
        source=source,
        kind=kind,
        logical_date=logical_date,
        digest=digest,
        filename=filename,
    )
    await bucket.put(key, payload)
    return {
        "r2_key": key,
        "content_sha256": digest,
        "bytes": len(payload),
    }


async def archive_json(
    bucket: Any,
    value: Any,
    *,
    source: str,
    kind: str,
    logical_date: str,
    filename: str,
) -> dict[str, Any]:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    result = await archive_bytes(
        bucket,
        payload,
        source=source,
        kind=kind,
        logical_date=logical_date,
        filename=filename,
    )
    return {**result, "content_type": "application/json"}
