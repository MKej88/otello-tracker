"""Read-only, single-filing transport diagnosis. Never publish or modify a queue."""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import io
import json
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from reactivate_bemobi_translation_documents import d1_client
from mirror_bemobi_translation_queue import NoRedirect, get_listing, HEADERS
from bemobi_cvm_rad import filing_identity
from bemobi_cvm_mirror import MAX_PDF
from bemobi_translation_mirror import official_urls, validate_listing, verify_pdf
from pypdf import PdfReader

DOCUMENT_ID = 7540
SQL = """
SELECT sd.id AS document_id, sd.url, substr(sd.published_at,1,10) AS delivery
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code='CVM' AND sd.id=?
"""


def collect(folder):
    rows = d1_client("CLOUDFLARE_READ_TOKEN")(SQL, (DOCUMENT_ID,))["results"]
    if len(rows) != 1 or rows[0]["document_id"] != DOCUMENT_ID:
        raise ValueError("Fant ikke entydig CVM-dokument 7540")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "filing.json").write_text(json.dumps(rows[0]), encoding="utf-8")
    print("Dokument 7540: kildeidentitet hentet (kun lesing)")


def inspect_body(raw, content_type, declared_length=None):
    """Return only booleans, bounded counts and fixed enum values; never body bytes."""
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in {"application/pdf", "text/html", "text/plain", "application/json",
                   "application/octet-stream", "application/zip", "application/xml", "text/xml"}:
        mime = "other_or_missing"
    prefix = raw[:1024].lstrip(b"\xef\xbb\xbf \r\n\t").lower()
    if raw.startswith(b"%PDF"):
        kind = "pdf"
    elif b"%PDF-" in raw[:1024]:
        kind = "pdf_header_not_at_start"
    elif prefix.startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"<script")):
        kind = "html"
    elif raw.startswith(b"PK\x03\x04"):
        kind = "zip"
    elif prefix.startswith((b"{", b"[")):
        kind = "json_like"
    elif prefix.startswith(b"<?xml"):
        kind = "xml"
    elif not raw:
        kind = "empty"
    else:
        kind = "other"
    eof = raw.rfind(b"%%EOF")
    report = {
        "mime": mime, "body_kind": kind, "bytes": len(raw),
        "within_size_limit": 0 < len(raw) <= MAX_PDF,
        "header_at_start": raw.startswith(b"%PDF"),
        "header_in_first_1024": b"%PDF-" in raw[:1024],
        "eof_present": eof >= 0,
        "eof_in_last_2048": b"%%EOF" in raw[-2048:],
        "bytes_after_eof": len(raw) - eof - 5 if eof >= 0 else None,
        "content_length_matches": declared_length == len(raw) if declared_length is not None else None,
        "strict_integrity": False,
        "parser": "not_attempted",
        "pages": None,
    }
    if report["within_size_limit"]:
        artifact = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        try:
            verify_pdf(raw, artifact)
            report["strict_integrity"] = True
        except ValueError:
            pass
        # Parser check is diagnostic only: it never overrides the actual mirror gate.
        if report["header_in_first_1024"]:
            try:
                import logging
                logger = logging.getLogger("pypdf")
                previous = logger.disabled
                logger.disabled = True
                try:
                    reader = PdfReader(io.BytesIO(raw), strict=True)
                    if reader.is_encrypted:
                        report["parser"] = "encrypted"
                    else:
                        count = len(reader.pages)
                        report["pages"] = min(count, 100000)
                        report["parser"] = "readable" if count else "no_pages"
                finally:
                    logger.disabled = previous
            except Exception:
                report["parser"] = "unreadable"
    return report


def inspect_route(opener, url):
    try:
        req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/pdf"})
        with opener.open(req, timeout=40) as resp:
            status = int(resp.status)
            if status != 200 or resp.geturl() != url:
                return {"status": status, "result": "unexpected_response"}
            raw = resp.read(MAX_PDF + 1)
            length = resp.headers.get("Content-Length", "")
            declared = int(length) if re.fullmatch(r"[0-9]{1,12}", length) else None
            return {"status": status, "result": "inspected",
                    **inspect_body(raw, resp.headers.get("Content-Type", ""), declared)}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "result": "http_error"}
    except Exception:
        return {"result": "transport_error"}


def diagnose(folder):
    row = json.loads((folder / "filing.json").read_text(encoding="utf-8"))
    if row.get("document_id") != DOCUMENT_ID:
        raise ValueError("Uventet dokument-ID")
    identity = filing_identity(row["url"])
    delivery = date.fromisoformat(row["delivery"]).isoformat()
    if not identity:
        raise ValueError("Ugyldig CVM-identitet")
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    listing = get_listing(opener, delivery)
    validate_listing(listing, identity, delivery)
    print("Dokument 7540: aktivt dokument, utsteder og dato bekreftet")
    for route, url in zip(("canonical", "alternative"), official_urls(identity), strict=True):
        report = inspect_route(opener, url)
        print("Dokument 7540 " + route + ": " + json.dumps(report, sort_keys=True))
    print("Diagnose fullført; ingen endringer i D1, R2 eller oversettelseskø")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "diagnose"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    {"collect": collect, "diagnose": diagnose}[args.mode](args.folder)


if __name__ == "__main__":
    main()
