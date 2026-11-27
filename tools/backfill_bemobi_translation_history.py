"""Stage only verified current CVM filings inside the rolling 24-month window."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import urllib.request
from pathlib import Path

from reactivate_bemobi_translation_documents import d1_client
from mirror_bemobi_translation_queue import (NoRedirect, build_document, publish as publish_mirror,
    MirrorFailure)
from bemobi_cvm_rad import filing_identity
from bemobi_cvm_mirror import MAX_INDEX
from bemobi_translation_mirror import validate_manifest, verify_pdf

BATCH = 6
# Unknown versions, replaced filings, IR metadata and completed documents are not candidates.
# Use SQLite's rolling calendar boundary; retain the leap-day convention of date().
SCOPE = """
source_id IN (SELECT id FROM sources WHERE code='CVM')
AND document_type='CVM_IPE_METADATA'
AND date(published_at) BETWEEN date('now','-24 months') AND date('now')
AND CASE WHEN json_valid(metadata_json)
         THEN json_extract(metadata_json,'$.is_latest_version')=1 ELSE 0 END
AND COALESCE(trim(translation_status),'')=''
AND COALESCE(translation_attempts,0)=0
"""
COUNTS = f"""
SELECT substr(published_at,1,4) AS year, count(*) AS candidates
FROM source_documents WHERE {SCOPE} GROUP BY 1 ORDER BY 1
"""
# Keep a small ready-to-process buffer, independent of the normal incoming queue.
BUFFER = """
SELECT count(*) AS staged FROM source_documents
WHERE source_id IN (SELECT id FROM sources WHERE code='CVM')
AND translation_status IN ('PENDING','FAILED','PROCESSING')
AND COALESCE(translation_attempts,0)<3
AND date(published_at) BETWEEN date('now','-24 months') AND date('now')
AND CASE WHEN json_valid(metadata_json)
         THEN json_extract(metadata_json,'$.translation_backfill_queued_at') IS NOT NULL ELSE 0 END
"""
SELECT = f"""
SELECT id AS document_id,url,substr(published_at,1,10) AS delivery
FROM source_documents WHERE {SCOPE}
AND CASE WHEN json_valid(metadata_json) THEN
    COALESCE(json_extract(metadata_json,'$.translation_backfill_checked_at'),'') <
    strftime('%Y-%m-%dT%H:%M:%fZ','now','-24 hours') ELSE 0 END
ORDER BY published_at DESC,id DESC LIMIT ?
"""
UPDATE = f"""
UPDATE source_documents
SET translation_status='PENDING', extraction_status='PENDING', summary_status='PENDING',
    metadata_json=json_set(metadata_json,'$.translation_backfill_queued_at',
       strftime('%Y-%m-%dT%H:%M:%fZ','now'))
WHERE id=? AND url=? AND substr(published_at,1,10)=? AND {SCOPE}
"""
DEFER = f"""
UPDATE source_documents
SET metadata_json=json_set(metadata_json,'$.translation_backfill_checked_at',
       strftime('%Y-%m-%dT%H:%M:%fZ','now'))
WHERE id=? AND url=? AND substr(published_at,1,10)=? AND {SCOPE}
"""


def collect(folder):
    query = d1_client("CLOUDFLARE_READ_TOKEN")
    counts = query(COUNTS, ())["results"]
    staged = query(BUFFER, ())["results"][0]["staged"]
    capacity = max(0, BATCH - int(staged))
    rows = query(SELECT, (capacity,))["results"]
    if len(rows) > capacity:
        raise ValueError("Historisk kø overskrider kapasiteten")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "queue.json").write_text(json.dumps(rows), encoding="utf-8")
    print("Historiske kandidater per år: " + json.dumps(counts))
    print(f"Historisk buffer: {staged}; valgt for verifisering: {len(rows)}")


def load_rows(folder):
    rows = json.loads((folder / "queue.json").read_text(encoding="utf-8"))
    if (not isinstance(rows,list) or len(rows)>BATCH
            or any(type(r.get("document_id")) is not int or r["document_id"]<=0 for r in rows)
            or len({r["document_id"] for r in rows}) != len(rows)):
        raise ValueError("Ugyldig historisk kø")
    return rows


def build(folder):
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    listings = {}
    for row in load_rows(folder):
        doc = row["document_id"]
        try:
            manifest, raw = build_document(opener, row, listings)
            encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode()
            if len(encoded)>MAX_INDEX:
                raise ValueError("Manifestet er for stort")
            out = folder / str(doc)
            out.mkdir(exist_ok=False)
            (out/"original.pdf").write_bytes(raw)
            (out/"manifest.json").write_bytes(encoded)
            print(f"Historisk dokument {doc}: verifisert")
        except Exception as exc:
            detail = exc.code if isinstance(exc, MirrorFailure) else type(exc).__name__
            print(f"Historisk dokument {doc}: utsatt ({detail})")


def verify_readback(row, folder):
    out = folder / str(row["document_id"])
    manifest = json.loads((out/"readback-manifest.json").read_bytes())
    artifact = validate_manifest(manifest, filing_identity(row["url"]))
    if manifest["delivery"] != row["delivery"]:
        raise ValueError("Publiseringsdato avviker")
    verify_pdf((out/"readback-original.pdf").read_bytes(), artifact)


def stage(rows, folder, query):
    queued = deferred = changed = 0
    for row in rows:
        params = (row["document_id"],row["url"],row["delivery"])
        if not (folder/str(row["document_id"])).exists():
            result = query(DEFER, params)
            deferred += int(result["meta"]["changes"])
            continue
        verify_readback(row, folder)
        result = query(UPDATE, params)
        n = result["meta"]["changes"]
        if n not in (0,1):
            raise ValueError("Uventet databaseendring")
        queued += n
        changed += 1-n
    print(f"Historisk kø: {queued} lagt i kø; {deferred} utsatt; {changed} endret siden kontroll")
    return queued, deferred, changed


def publish(folder):
    rows = load_rows(folder)
    if not rows:
        print("Ingen historiske dokumenter valgt")
        return
    publish_mirror(folder)
    stage(rows, folder, d1_client("CLOUDFLARE_API_TOKEN"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect","build","publish"))
    parser.add_argument("folder",type=Path)
    args = parser.parse_args()
    {"collect":collect,"build":build,"publish":publish}[args.mode](args.folder)


if __name__ == "__main__":
    main()
