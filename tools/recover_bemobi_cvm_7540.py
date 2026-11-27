"""One-time verified recovery of CVM document 7540, with original retained."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from reactivate_bemobi_translation_documents import d1_client
from mirror_bemobi_translation_queue import ROOT, NoRedirect, get_listing, HEADERS, bounded_read
from bemobi_cvm_rad import filing_identity
from bemobi_cvm_mirror import MAX_INDEX, MAX_PDF
from bemobi_translation_mirror import official_urls, validate_listing
from bemobi_7540_normalization import (DOCUMENT_ID, normalize_padding, make_manifest, manifest_key_7540,
    validate_normalization_manifest, verify_manifest_pair)

CUTOFF = "2026-11-27T16:44:07.000Z"
SELECT = """
SELECT sd.id AS document_id, sd.url, substr(sd.published_at,1,10) AS delivery,
       sd.translation_status AS status, sd.translation_attempts AS attempts,
       sd.translation_processed_at AS processed_at
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code='CVM' AND sd.id=?
  AND sd.translation_status='FAILED' AND sd.translation_attempts=3
  AND sd.translation_error LIKE 'download:%HTTP 526%'
  AND (sd.translation_processed_at IS NULL OR sd.translation_processed_at<=?)
"""
UPDATE = """
UPDATE source_documents
SET translation_status='PENDING', translation_attempts=0, translation_error=NULL,
    extraction_status='PENDING', summary_status='PENDING',
    translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE id=? AND url=? AND substr(published_at,1,10)=?
  AND source_id IN (SELECT id FROM sources WHERE code='CVM')
  AND translation_status='FAILED' AND translation_attempts=3
  AND translation_error LIKE 'download:%HTTP 526%'
  AND translation_processed_at IS ?
  AND (translation_processed_at IS NULL OR translation_processed_at<=?)
"""


def collect(folder):
    rows = d1_client("CLOUDFLARE_READ_TOKEN")(SELECT, (DOCUMENT_ID, CUTOFF))["results"]
    folder.mkdir(parents=True, exist_ok=True)
    if not rows:
        print("Dokument 7540: ingen kvalifisert historisk feil; ingen endring")
        return
    if len(rows) != 1 or rows[0]["document_id"] != DOCUMENT_ID:
        raise ValueError("Uventet dokumentidentitet")
    (folder / "row.json").write_text(json.dumps(rows[0]), encoding="utf-8")
    print("Dokument 7540: historisk feil kvalifisert for kontroll")


def load_row(folder):
    row = json.loads((folder / "row.json").read_text(encoding="utf-8"))
    if row.get("document_id") != DOCUMENT_ID or row.get("status") != "FAILED" or row.get("attempts") != 3:
        raise ValueError("Ugyldig dokumentavgrensning")
    return row


def build(folder):
    row = load_row(folder)
    identity = filing_identity(row["url"])
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    listing = get_listing(opener, row["delivery"])
    validate_listing(listing, identity, row["delivery"])
    url = official_urls(identity)[1]
    with opener.open(urllib.request.Request(url, headers={**HEADERS, "Accept": "application/pdf"}), timeout=40) as resp:
        if resp.status != 200 or resp.geturl() != url:
            raise ValueError("Uventet CVM-respons")
        raw = bounded_read(resp, MAX_PDF)
        length = resp.headers.get("Content-Length")
        if length and int(length) != len(raw):
            raise ValueError("CVM-responsens størrelse avviker")
    processing = normalize_padding(raw)
    manifest = make_manifest(identity, row["delivery"], listing, raw, processing)
    validate_normalization_manifest(manifest, identity, row["delivery"], DOCUMENT_ID)
    verify_manifest_pair(manifest, raw, processing)
    encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_INDEX:
        raise ValueError("Manifestet er for stort")
    (folder / "original.pdf").write_bytes(raw)
    (folder / "processing.pdf").write_bytes(processing)
    (folder / "manifest.json").write_bytes(encoded)
    print(f"Dokument 7540: original {len(raw)} byte; behandlingskopi {len(processing)} byte; {manifest['pages']} sider; tekst identisk")


def publish(folder):
    row = load_row(folder)
    identity = filing_identity(row["url"])
    manifest = json.loads((folder / "manifest.json").read_bytes())
    validate_normalization_manifest(manifest, identity, row["delivery"], DOCUMENT_ID)
    verify_manifest_pair(manifest, (folder / "original.pdf").read_bytes(), (folder / "processing.pdf").read_bytes())
    bucket = os.environ["CLOUDFLARE_R2_BUCKET_NAME"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", bucket):
        raise ValueError("Ugyldig R2-bucket")
    wrangler = ROOT / "cloudflare" / "node_modules" / ".bin" / "wrangler"
    for key, filename, mime in ((manifest["original"]["key"], "original.pdf", "application/pdf"),
                                (manifest["processing"]["key"], "processing.pdf", "application/pdf"),
                                (manifest_key_7540(identity), "manifest.json", "application/json")):
        local = folder / filename
        readback = folder / ("readback-" + filename)
        target = bucket + "/" + key
        subprocess.run([str(wrangler), "r2", "object", "put", target,
                        "--file=" + str(local), "--content-type=" + mime, "--remote"], check=True)
        subprocess.run([str(wrangler), "r2", "object", "get", target,
                        "--file=" + str(readback), "--remote"], check=True)
        if local.read_bytes() != readback.read_bytes():
            raise ValueError("R2-tilbakelesing avviker")
    stored_manifest = json.loads((folder / "readback-manifest.json").read_bytes())
    validate_normalization_manifest(stored_manifest, identity, row["delivery"], DOCUMENT_ID)
    verify_manifest_pair(stored_manifest, (folder / "readback-original.pdf").read_bytes(),
                         (folder / "readback-processing.pdf").read_bytes())
    print("Dokument 7540: begge filer og manifest verifisert i R2")
    result = d1_client("CLOUDFLARE_API_TOKEN")(UPDATE, (DOCUMENT_ID, row["url"], row["delivery"],
                                                     row.get("processed_at"), CUTOFF))
    changes = result.get("meta", {}).get("changes")
    if changes not in (0, 1):
        raise ValueError("Uventet antall D1-endringer")
    print("Dokument 7540: reaktivert" if changes == 1 else "Dokument 7540: status endret; ingen reaktivering")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "build", "publish"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    if args.mode != "collect" and not (args.folder / "row.json").exists():
        print("Ingen kvalifisert rad; ingen behandling")
        return
    {"collect": collect, "build": build, "publish": publish}[args.mode](args.folder)


if __name__ == "__main__":
    main()
