"""Avgrenset engangsreaktivering etter produksjonsutrulling av #1007."""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import urllib.request
from pathlib import Path

from diagnose_bemobi_five_documents import classify_error, source_metrics
from mirror_bemobi_translation_queue import NoRedirect, build_document
from reactivate_bemobi_translation_documents import d1_client
from bemobi_document_translation import extract_pdf_text

# Eksakt diagnose 46137976144, før utrulling av ny oversettelsesmetode.
CUTOFF = "2026-11-28T11:02:48.236Z"
EXPECTED = {
    7538: ("2026-11-12", 3, {"reason": "max_document_chunks"}),
    7537: ("2026-11-13", 3, {"reason": "missing_values", "missing_count": 15}),
    5282: ("2026-10-14", 3, {"reason": "missing_values", "missing_count": 1}),
    1475: ("2026-08-27", 2, {"reason": "missing_values", "missing_count": 1}),
    292: ("2026-08-12", 2, {"reason": "missing_values", "missing_count": 6}),
}
SELECT_SQL = """
SELECT sd.id AS document_id, sd.url, substr(sd.published_at,1,10) AS delivery,
       sd.translation_status AS status, sd.translation_attempts AS attempts,
       sd.translation_processed_at AS processed_at, sd.translation_error AS error
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code='CVM' AND sd.id=?
"""
UPDATE_SQL = """
UPDATE source_documents SET translation_status='PENDING', translation_attempts=0,
    translation_error=NULL, extraction_status='PENDING', summary_status='PENDING',
    translation_processed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE id=? AND url=? AND substr(published_at,1,10)=?
  AND source_id IN (SELECT id FROM sources WHERE code='CVM')
  AND translation_status='FAILED' AND translation_attempts=?
  AND translation_processed_at=? AND translation_processed_at<=?
  AND translation_error=?
"""


def eligible(row):
    expected = EXPECTED.get(row.get("document_id"))
    if expected is None:
        return False
    delivery, attempts, error = expected
    timestamp = row.get("processed_at")
    return (row.get("delivery") == delivery and row.get("status") == "FAILED"
            and type(row.get("attempts")) is int and row["attempts"] == attempts
            and isinstance(timestamp, str) and timestamp <= CUTOFF
            and bool(timestamp) and bool(row.get("url"))
            and classify_error(row.get("error")) == error)


def fingerprint(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def collect(folder):
    folder.mkdir(parents=True, exist_ok=True)
    query = d1_client("CLOUDFLARE_READ_TOKEN")
    rows = []
    for document_id in EXPECTED:
        result = query(SELECT_SQL, (document_id,))["results"]
        if len(result) == 1 and result[0]["document_id"] == document_id and eligible(result[0]):
            row = result[0]
            rows.append({"document_id": document_id, "url": row["url"],
                         "delivery": row["delivery"], "fingerprint": fingerprint(row)})
        else:
            print(f"Dokument {document_id}: ikke kvalifisert eller nyere status")
    (folder / "rows.json").write_text(json.dumps(rows), encoding="utf-8")


def verify(folder):
    rows = json.loads((folder / "rows.json").read_text(encoding="utf-8"))
    if len(rows) > len(EXPECTED) or len({r["document_id"] for r in rows}) != len(rows):
        raise ValueError("Ugyldig dokumentliste")
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    verified = []
    listings = {}
    for row in rows:
        document_id = row["document_id"]
        if document_id not in EXPECTED or row["delivery"] != EXPECTED[document_id][0]:
            raise ValueError("Uventet dokumentidentitet")
        try:
            manifest, raw = build_document(opener, row, listings)
            if manifest["schema"] != 1:
                raise ValueError("Uventet normalisert dokument")
            metrics = source_metrics(extract_pdf_text(raw))
            if (metrics["language"] != "pt" or not metrics["characters"]
                    or metrics["exceeds_limit"] or metrics["values_lost_by_chunking"]):
                raise ValueError("Originalen oppfyller ikke behandlingskrav")
            verified.append({"document_id": document_id, "fingerprint": row["fingerprint"]})
            print(f"Dokument {document_id}: offisiell original verifisert; {metrics['chunks']} deler")
        except Exception:
            print(f"Dokument {document_id}: original ikke bekreftet; ingen reaktivering")
    (folder / "verified.json").write_text(json.dumps(verified), encoding="utf-8")


def reactivate_one(item, query):
    document_id = item["document_id"]
    if document_id not in EXPECTED:
        raise ValueError("Uventet dokument-ID")
    rows = query(SELECT_SQL, (document_id,))["results"]
    if len(rows) != 1:
        return 0
    row = rows[0]
    if row["document_id"] != document_id or not eligible(row) or fingerprint(row) != item["fingerprint"]:
        return 0
    result = query(UPDATE_SQL, (document_id, row["url"], row["delivery"],
                                row["attempts"], row["processed_at"], CUTOFF, row["error"]))
    changes = result.get("meta", {}).get("changes")
    if changes not in (0, 1):
        raise ValueError("Uventet antall endrede rader")
    return changes


def recover(folder):
    items = json.loads((folder / "verified.json").read_text(encoding="utf-8"))
    if len(items) > len(EXPECTED) or len({r["document_id"] for r in items}) != len(items):
        raise ValueError("Ugyldig verifikasjonsliste")
    query = d1_client("CLOUDFLARE_API_TOKEN")
    count = 0
    for item in items:
        changed = reactivate_one(item, query)
        count += changed
        print(f"Dokument {item['document_id']}: " + ("reaktivert" if changed else "uendret"))
    print(f"Reaktivert: {count}; maksimalt fem. Ingen oversettelser publisert.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "verify", "recover"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    {"collect": collect, "verify": verify, "recover": recover}[args.mode](args.folder)
