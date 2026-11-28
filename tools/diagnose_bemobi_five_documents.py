"""Read-only incident diagnosis for five known Bemobi translation failures."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import subprocess
import urllib.request
from datetime import date
from pathlib import Path

from reactivate_bemobi_translation_documents import d1_client, verify_stored_document
from mirror_bemobi_translation_queue import ROOT, NoRedirect, build_document, bounded_read
from bemobi_cvm_mirror import MAX_PDF
from bemobi_document_translation import (
    AI_ERROR_CODES, MAX_DOCUMENT_CHUNKS, MAX_CHUNK_CHARACTERS,
    detect_language, extract_pdf_text, stable_chunks, validate_preserved_values,
)

IDS = (7538, 7537, 5282, 1475, 292)
SQL = """
SELECT sd.id AS document_id, sd.url, substr(sd.published_at,1,10) AS delivery,
       sd.translation_status AS status, sd.translation_attempts AS attempts,
       sd.translation_error AS error
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code='CVM' AND sd.id=?
"""


def classify_error(error):
    # Only fixed labels and bounded numeric fields may leave this function.
    error = error if isinstance(error, str) else ""
    if "Dokumentet overskrider sikker behandlingsgrense" in error:
        return {"reason": "max_document_chunks"}
    match = re.search(r"verdikontroll feilet \((\d{1,6}) mangler\)", error)
    if match:
        return {"reason": "missing_values", "missing_count": int(match.group(1))}
    if "verdikontroll feilet" in error or error.startswith("value_validation:"):
        return {"reason": "value_validation_unknown"}
    if "WorkersAIError" in error:
        match = re.search(r"\bai_code=(\d{4})\b", error)
        code = int(match.group(1)) if match else None
        return {"reason": "ai_error", "ai_code": code if code in AI_ERROR_CODES else None}
    if "krever OCR" in error:
        return {"reason": "ocr_required"}
    if "originaldokument HTTP " in error:
        match = re.search(r"originaldokument HTTP ([1-5]\d{2})\b", error)
        return {"reason": "download_http", "http": int(match.group(1)) if match else None}
    return {"reason": "unknown" if error else "no_error"}


def source_metrics(text):
    chunks = stable_chunks(text)
    joined = "\n\n".join(chunk for _, chunk in chunks)
    return {
        "language": detect_language(text),
        "characters": len(text),
        "chunks": len(chunks),
        "chunk_limit": MAX_DOCUMENT_CHUNKS,
        "chunk_characters": MAX_CHUNK_CHARACTERS,
        "exceeds_limit": len(chunks) > MAX_DOCUMENT_CHUNKS,
        "values_lost_by_chunking": len(validate_preserved_values(text, joined)),
        "max_unique_values_per_chunk": max(
            (len(validate_preserved_values(chunk, "")) for _, chunk in chunks), default=0),
    }


def collect(folder):
    query = d1_client("CLOUDFLARE_READ_TOKEN")
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for document_id in IDS:
        result = query(SQL, (document_id,))["results"]
        if len(result) != 1 or result[0]["document_id"] != document_id:
            print(f"Dokument {document_id}: identitet ikke bekreftet")
            continue
        row = result[0]
        try:
            delivery = date.fromisoformat(row["delivery"]).isoformat()
        except (TypeError, ValueError):
            print(f"Dokument {document_id}: ugyldig publiseringsdato")
            continue
        status = row.get("status")
        attempts = row.get("attempts")
        info = {
            "document_id": document_id, "delivery": delivery,
            "status": status if status in {"FAILED", "PENDING", "PROCESSING", "READY", "NOT_REQUIRED"} else "unknown",
            "attempts": attempts if type(attempts) is int and 0 <= attempts <= 100 else None,
            **classify_error(row.get("error")),
        }
        print(json.dumps(info, sort_keys=True))
        # Do not persist raw exceptions. URL remains local for identity validation.
        rows.append({"document_id": document_id, "delivery": delivery, "url": row["url"]})
    (folder / "rows.json").write_text(json.dumps(rows), encoding="utf-8")


def read_r2(folder):
    bucket = os.environ["CLOUDFLARE_R2_BUCKET_NAME"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", bucket):
        raise ValueError("Ugyldig R2-bucket")
    wrangler = ROOT / "cloudflare" / "node_modules" / ".bin" / "wrangler"

    def download(key, path):
        # Read-only token, fixed GET operation; suppress raw CLI output.
        subprocess.run([str(wrangler), "r2", "object", "get", bucket + "/" + key,
                        "--file=" + str(path), "--remote"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)

    for row in load_rows(folder):
        document_id = row["document_id"]
        try:
            verify_stored_document(row, folder, download)
            (folder / str(document_id) / "verified").write_text("yes")
            print(f"Dokument {document_id}: R2-original verifisert")
        except Exception:
            print(f"Dokument {document_id}: R2-original ikke bekreftet")


def load_rows(folder):
    rows = json.loads((folder / "rows.json").read_text(encoding="utf-8"))
    if (not isinstance(rows, list) or len(rows) > len(IDS)
            or any(row.get("document_id") not in IDS for row in rows)
            or len({row["document_id"] for row in rows}) != len(rows)):
        raise ValueError("Uventede dokumenter")
    return rows


def diagnose(folder):
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    listings = {}
    for row in load_rows(folder):
        document_id = row["document_id"]
        try:
            local = folder / str(document_id)
            if (local / "verified").is_file():
                with (local / "original.pdf").open("rb") as handle:
                    raw = bounded_read(handle, MAX_PDF)
                route = "verified_r2"
            else:
                _, raw = build_document(opener, row, listings)
                route = "verified_official"
            metrics = source_metrics(extract_pdf_text(raw))
            print(json.dumps({"document_id": document_id, "original": route, **metrics}, sort_keys=True))
        except Exception:
            print(json.dumps({"document_id": document_id, "original": "not_verified_or_unreadable"}))
    print("Diagnose fullført; ingen nye AI-kall, ingen endringer i D1, R2 eller køen.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "read-r2", "diagnose"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    {"collect": collect, "read-r2": read_r2, "diagnose": diagnose}[args.mode](args.folder)
