from __future__ import annotations

from typing import Any

try:
    from .r2_archive import archive_bytes, archive_json
except ImportError:
    from r2_archive import archive_bytes, archive_json

_ALLOWED_SOURCE_CODES = {
    "B3",
    "ECB",
    "EURONEXT",
    "INVESTING",
    "MANUAL",
}


async def archive_historical_import(
    bucket: Any,
    payload: bytes,
    *,
    source_code: str,
    filename: str,
    logical_date: str,
    import_purpose: str,
) -> dict[str, Any]:
    """Archive a user/provider historical import file plus a reproducible manifest.

    This is intentionally independent of the parser/import itself. The exact bytes are
    archived before/alongside a future production import so the D1 facts can always point
    back to the original CSV/ZIP that was supplied at cutover or during a later backfill.
    """
    source = source_code.strip().upper()
    if source not in _ALLOWED_SOURCE_CODES:
        raise ValueError(f"Historisk arkiv støtter ikke source_code={source_code!r}")
    raw = await archive_bytes(
        bucket,
        payload,
        source=source.lower(),
        kind="historical-import",
        logical_date=logical_date,
        filename=filename,
    )
    manifest = {
        "archive_version": "historical-import-v1",
        "source_code": source,
        "logical_date": logical_date,
        "filename": filename,
        "import_purpose": import_purpose,
        "r2_key": raw["r2_key"],
        "content_sha256": raw["content_sha256"],
        "bytes": raw["bytes"],
        "policy": "ARCHIVE_EXACT_BYTES_BEFORE_OR_WITH_PRODUCTION_IMPORT",
    }
    manifest_archive = await archive_json(
        bucket,
        manifest,
        source=source.lower(),
        kind="historical-import-manifest",
        logical_date=logical_date,
        filename=f"{filename}.manifest.json",
    )
    return {
        "status": "ok",
        **manifest,
        "manifest_r2_key": manifest_archive["r2_key"],
        "manifest_sha256": manifest_archive["content_sha256"],
    }
