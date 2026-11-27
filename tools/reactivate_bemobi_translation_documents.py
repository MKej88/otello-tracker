"""One-time, bounded recovery of nine independently verified CVM originals."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from mirror_bemobi_translation_queue import (
    ROOT, NoRedirect, bounded_read, build_document, MirrorFailure,
)
from bemobi_cvm_rad import filing_identity
from bemobi_cvm_mirror import MAX_INDEX, MAX_PDF
from bemobi_translation_mirror import manifest_key, validate_manifest, verify_pdf

VERIFIED_IDS = (4059, 4060, 4062, 5282, 7537, 7538, 7541, 7542, 8079)
INVESTIGATE_ID = 7540
# The original R2 publication completed at 14:35:03 UTC on 27 November.
# Never reset newer failed attempts, even if this workflow is rerun.
CUTOFF = "2026-11-27T14:35:04.000Z"
SELECT_SQL = """
SELECT sd.id AS document_id, sd.url, substr(sd.published_at,1,10) AS delivery,
       sd.translation_status AS status, sd.translation_attempts AS attempts,
       sd.translation_processed_at AS processed_at,
       CASE WHEN sd.translation_error IS NOT NULL THEN 1 ELSE 0 END AS has_error
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code='CVM' AND sd.id IN (?,?,?,?,?,?,?,?,?,?)
ORDER BY sd.id
"""
UPDATE_SQL = """
UPDATE source_documents
SET translation_status='PENDING', translation_attempts=0, translation_error=NULL,
    extraction_status='PENDING', summary_status='PENDING',
    translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE id=? AND url=? AND substr(published_at,1,10)=?
  AND source_id IN (SELECT id FROM sources WHERE code='CVM')
  AND translation_status=? AND translation_attempts=?
  AND translation_processed_at IS ? AND translation_error IS NOT NULL
  AND translation_status IN ('FAILED','PENDING')
  AND (translation_processed_at IS NULL OR translation_processed_at <= ?)
"""


def d1_client(token_name):
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account):
        raise ValueError("Ugyldig Cloudflare-konto")
    root = "https://api.cloudflare.com/client/v4/accounts/" + account + "/d1/database"
    opener = urllib.request.build_opener(NoRedirect())
    headers = {"Authorization": "Bearer " + os.environ[token_name],
               "Content-Type": "application/json"}

    def api(url, payload=None):
        request = urllib.request.Request(url, headers=headers,
            data=json.dumps(payload).encode() if payload is not None else None)
        with opener.open(request, timeout=30) as response:
            data = json.loads(bounded_read(response, MAX_INDEX))
        if data.get("success") is not True:
            raise ValueError("D1-forespørselen mislyktes")
        return data["result"]

    databases = api(root + "?name=otello-nav&per_page=10")
    ids = [row["uuid"] for row in databases if row.get("name") == "otello-nav"]
    if len(ids) != 1 or not re.fullmatch(r"[a-fA-F0-9-]{36}", ids[0]):
        raise ValueError("Fant ikke entydig D1-database")

    def query(sql, params):
        groups = api(root + "/" + ids[0] + "/query", {"sql": sql, "params": list(params)})
        if len(groups) != 1 or groups[0].get("success") is not True:
            raise ValueError("D1-spørringen mislyktes")
        return groups[0]
    return query


def collect(folder):
    rows = d1_client("CLOUDFLARE_READ_TOKEN")(SELECT_SQL, (*VERIFIED_IDS, INVESTIGATE_ID))["results"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "recovery-rows.json").write_text(json.dumps(rows), encoding="utf-8")
    print("Avgrensede dokumenter funnet:", len(rows))


def load_rows(folder):
    rows = json.loads((folder / "recovery-rows.json").read_text(encoding="utf-8"))
    allowed = set(VERIFIED_IDS) | {INVESTIGATE_ID}
    if (not isinstance(rows, list) or len(rows) > len(allowed)
            or any(type(r.get("document_id")) is not int or r["document_id"] not in allowed for r in rows)
            or len({r["document_id"] for r in rows}) != len(rows)):
        raise ValueError("Ugyldig avgrenset gjenopprettingskø")
    return rows


def eligible(row):
    return (row["document_id"] in VERIFIED_IDS and row.get("status") in ("FAILED", "PENDING")
            and row.get("has_error") == 1 and type(row.get("attempts")) is int
            and 0 <= row["attempts"] <= 3 and bool(row.get("url")) and bool(row.get("delivery"))
            and (row.get("processed_at") is None
                 or isinstance(row["processed_at"], str) and row["processed_at"] <= CUTOFF))


def verify_stored_document(row, folder, download):
    identity = filing_identity(row["url"])
    out = folder / str(row["document_id"])
    out.mkdir(exist_ok=True)
    manifest_path = out / "manifest.json"
    download(manifest_key(identity), manifest_path)
    with manifest_path.open("rb") as handle:
        manifest = json.loads(bounded_read(handle, MAX_INDEX))
    artifact = validate_manifest(manifest, identity)
    if manifest["delivery"] != row["delivery"]:
        raise ValueError("Publiseringsdato avviker")
    pdf_path = out / "original.pdf"
    download(artifact["key"], pdf_path)
    with pdf_path.open("rb") as handle:
        verify_pdf(bounded_read(handle, MAX_PDF), artifact)


def recover_rows(rows, folder, download, query):
    reset = skipped = failed = 0
    for row in rows:
        document_id = row["document_id"]
        if document_id == INVESTIGATE_ID:
            continue
        if not eligible(row):
            print(f"Dokument {document_id}: uendret (ferdig, nyere forsøk eller ikke kvalifisert)")
            skipped += 1
            continue
        try:
            verify_stored_document(row, folder, download)
        except Exception as exc:
            print(f"Dokument {document_id}: uendret (R2-verifikasjon feilet: {type(exc).__name__})")
            failed += 1
            continue
        # Compare-and-set prevents a concurrent Worker claim or newer failure from being reset.
        result = query(UPDATE_SQL, (document_id, row["url"], row["delivery"], row["status"],
                                    row["attempts"], row.get("processed_at"), CUTOFF))
        changes = result.get("meta", {}).get("changes")
        if changes == 1:
            print(f"Dokument {document_id}: verifisert og reaktivert")
            reset += 1
        elif changes == 0:
            print(f"Dokument {document_id}: uendret (status endret siden avlesing)")
            skipped += 1
        else:
            raise ValueError("Uventet antall D1-endringer")
    print(f"Reaktivert: {reset}; uendret: {skipped}; R2-verifikasjon feilet: {failed}")
    return reset, skipped, failed


def recover(folder):
    bucket = os.environ["CLOUDFLARE_R2_BUCKET_NAME"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", bucket):
        raise ValueError("Ugyldig R2-bucket")
    wrangler = ROOT / "cloudflare" / "node_modules" / ".bin" / "wrangler"

    def download(key, path):
        subprocess.run([str(wrangler), "r2", "object", "get", bucket + "/" + key,
                        "--file=" + str(path), "--remote"], check=True)

    _, _, failed = recover_rows(load_rows(folder), folder, download,
                                d1_client("CLOUDFLARE_API_TOKEN"))
    if failed:
        raise SystemExit("Minst én R2-verifikasjon feilet; dokumentet ble ikke reaktivert")


def investigate(folder):
    rows = [r for r in load_rows(folder) if r["document_id"] == INVESTIGATE_ID]
    if not rows:
        print("Dokument 7540: ikke funnet i CVM-kilden")
        return
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        build_document(opener, rows[0], {})
        print("Dokument 7540: original kunne verifiseres ved ny kontroll; ingen reaktivering")
    except MirrorFailure as exc:
        print("Dokument 7540: " + exc.code)
    except Exception as exc:
        print("Dokument 7540: uklassifisert " + type(exc).__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "investigate", "recover"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    {"collect": collect, "investigate": investigate, "recover": recover}[args.mode](args.folder)


if __name__ == "__main__":
    main()
