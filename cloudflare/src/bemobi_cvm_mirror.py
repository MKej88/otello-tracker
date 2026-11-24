"""Private R2 transport for fresh CVM filings, independently checked by the Worker."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from bemobi_cvm_rad import parse_rows, release_candidates, filing_identity

PREFIX = "mirror/official/bemobi/cvm-rad/v1/"
INDEX = PREFIX + "latest.json"
MAX_INDEX = 3 * 1024 * 1024
MAX_PDF = 24 * 1024 * 1024

def pdf_key(identity, digest):
    if not identity or len(identity) != 3 or not all(re.fullmatch(r"[0-9]+", x) for x in identity):
        raise ValueError("Invalid CVM filing identity")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid CVM SHA256")
    return PREFIX + "-".join(identity) + "/" + digest + ".pdf"

async def _read(bucket, key, maximum):
    if bucket is None:
        raise ValueError("Private R2 unavailable")
    obj = await bucket.get(key)
    if obj is None or int(getattr(obj, "size", 0) or 0) > maximum:
        raise ValueError("Missing or oversized CVM mirror object")
    raw = bytes(await obj.arrayBuffer())
    if not raw or len(raw) > maximum:
        raise ValueError("Invalid CVM mirror object size")
    return raw

def validate_index(index, *, target_date, now=None):
    now = now or datetime.now(UTC)
    observed = datetime.fromisoformat(index["observed_at"])
    target = date.fromisoformat(target_date)
    start, end = (date.fromisoformat(index[key]) for key in ("start_date", "end_date"))
    age = now - observed
    if (index["schema"] != 1 or index["cvm_code"] != "25500"
        or observed.tzinfo is None or age < -timedelta(minutes=5) or age > timedelta(hours=36)
        or end != observed.date() or start != end - timedelta(days=120)
        or not end - timedelta(days=1) <= target <= end):
        raise ValueError("Stale or invalid CVM mirror observation")
    rows = parse_rows(index["listing"], start, end)
    releases = release_candidates(rows)
    if not releases:
        raise ValueError("CVM mirror contains no eligible release")
    latest = releases[0]
    if date.fromisoformat(latest["delivery"]) > target:
        raise ValueError("Newest mirror filing postdates refresh target")
    artifact = index["artifact"]
    identity = filing_identity(latest["url"])
    digest = artifact["sha256"]
    size = artifact["bytes"]
    if (artifact["url"] != latest["url"] or artifact["period"] != latest["expected_period"]
        or artifact["key"] != pdf_key(identity, digest)
        or type(size) is not int or not 0 < size <= MAX_PDF):
        raise ValueError("CVM mirror manifest and filing mismatch")
    return {**latest, "mirror_artifact": artifact}

async def discover_mirrored_releases(bucket, *, target_date, now=None):
    try:
        index = json.loads(await _read(bucket, INDEX, MAX_INDEX))
        row = validate_index(index, target_date=target_date, now=now)
        # Verify the object even if the latest result is already in D1.
        await read_mirrored_pdf(bucket, row["mirror_artifact"], row["url"])
        return [row], {"status": "ok", "transport": "github_actions_private_r2",
            "checked_date": index["end_date"], "observed_at": index["observed_at"],
            "latest_period": row["expected_period"], "release_count": 1}
    except Exception as exc:
        return [], {"status": "not_available", "transport": "github_actions_private_r2",
                    "error": f"{type(exc).__name__}: {str(exc)[:180]}"}

async def read_mirrored_pdf(bucket, artifact, url):
    if artifact["url"] != url or artifact["key"] != pdf_key(filing_identity(url), artifact["sha256"]):
        raise ValueError("CVM mirror provenance mismatch")
    raw = await _read(bucket, artifact["key"], MAX_PDF)
    if (not raw.startswith(b"%PDF") or len(raw) != artifact["bytes"]
        or hashlib.sha256(raw).hexdigest() != artifact["sha256"]):
        raise ValueError("CVM mirror PDF SHA256/size mismatch")
    return raw
