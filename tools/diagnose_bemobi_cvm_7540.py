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


def _structure_flags(payload):
    """Recognize structure markers, never emit content or infer signature validity."""
    return {
        "pdf_header": b"%PDF-" in payload,
        "pdf_object": bool(re.search(rb"(?:^|[\r\n])\s*\d+\s+\d+\s+obj\b", payload)),
        "pdf_xref": bool(re.search(rb"(?:^|[\r\n])\s*(?:xref|startxref)\b", payload)),
        "pdf_byte_range": bool(re.search(rb"/ByteRange\s*\[", payload)),
        "pdf_signature_type": bool(re.search(rb"/Type\s*/Sig\b", payload)),
        "pdf_signature_subfilter": bool(re.search(rb"/SubFilter\s*/(?:adbe\.pkcs7\.detached|adbe\.pkcs7\.sha1|ETSI\.CAdES\.detached|ETSI\.RFC3161)\b", payload)),
        "cms_signed_data_oid": b"\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x07\x02" in payload,
        "pem_signature": b"-----BEGIN PKCS7-----" in payload or b"-----BEGIN CMS-----" in payload,
        "html": bool(re.search(rb"<(?:!doctype\s+html|html\b|head\b|body\b|script\b|form\b|/html\b)", payload, re.I)),
        "xml": bool(re.search(rb"<\?xml\b", payload, re.I)),
        "zip": b"PK\x03\x04" in payload,
        "gzip": payload.startswith(b"\x1f\x8b"),
        "jpeg": payload.startswith(b"\xff\xd8\xff"),
        "png": payload.startswith(b"\x89PNG\r\n\x1a\n"),
    }


def _der_sequence_length(payload):
    # Structural hint only; DER sequence alone is not evidence of a signature.
    if len(payload) < 2 or payload[0] != 0x30:
        return None
    length = payload[1]
    if length < 128:
        return 2 + length
    n = length & 127
    if not 1 <= n <= 4 or len(payload) < 2 + n or payload[2] == 0:
        return None
    size = int.from_bytes(payload[2:2+n], "big")
    return 2 + n + size if size >= 128 else None


def _strict_pdf_info(raw):
    import logging
    logger = logging.getLogger("pypdf")
    previous = logger.disabled
    logger.disabled = True
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            return {"status": "encrypted"}, None
        count = len(reader.pages)
        # Compare extracted text only via an in-memory hash, not via log content.
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:min(count, 100)])
        return {"status": "readable" if count else "no_pages", "pages": count,
                "text_characters": len(text), "text_comparison_complete": count <= 100}, hashlib.sha256(text.encode()).digest()
    except Exception:
        return {"status": "unreadable"}, None
    finally:
        logger.disabled = previous


def inspect_tail(raw):
    """Compare complete transport body with a prefix ending at the last EOF.
    No normalization is authorized by this diagnostic; both remain unmodified.
    """
    eof = raw.rfind(b"%%EOF")
    if eof < 0 or not raw.startswith(b"%PDF") or len(raw) > MAX_PDF:
        return {"status": "not_applicable"}, None
    core = raw[:eof + 5]
    tail = raw[eof + 5:]
    stripped = tail.strip(b" \t\r\n\x00\x0c")
    start = tail.lstrip(b" \t\r\n")
    flags = _structure_flags(stripped)
    der_length = _der_sequence_length(start)
    if not stripped:
        category = "padding_only"
    elif flags["pdf_header"] or flags["pdf_object"] or flags["pdf_xref"]:
        category = "pdf_structure_present"
    elif flags["cms_signed_data_oid"] or flags["pem_signature"]:
        category = "possible_cms"
    elif flags["html"]:
        category = "html_markers"
    elif flags["xml"]:
        category = "xml_markers"
    elif flags["zip"] or flags["gzip"] or flags["jpeg"] or flags["png"]:
        category = "embedded_format_marker"
    elif der_length is not None and der_length <= len(start):
        category = "possible_der"
    elif all(32 <= b <= 126 or b in (9, 10, 13) for b in stripped):
        category = "ascii_text"
    else:
        category = "unclassified_binary_or_text"
    full_info, full_text_hash = _strict_pdf_info(raw)
    core_info, core_text_hash = _strict_pdf_info(core + b"\n")
    comparable = (full_text_hash is not None and core_text_hash is not None
                  and full_info.get("text_comparison_complete") is True
                  and core_info.get("text_comparison_complete") is True)
    report = {
        "status": "inspected",
        "category": category,
        "core_bytes": len(core),
        "tail_bytes": len(tail),
        "tail_nonpadding_bytes": len(stripped),
        "tail_zero_bytes": tail.count(b"\x00"),
        "tail_ascii_printable_bytes": sum(32 <= b <= 126 or b in (9, 10, 13) for b in tail),
        "tail_markers": flags,
        "core_signature_markers": {key: value for key, value in _structure_flags(core).items()
                                   if key in ("pdf_byte_range", "pdf_signature_type", "pdf_signature_subfilter",
                                              "cms_signed_data_oid", "pem_signature")},
        "der_sequence_fits": der_length is not None and der_length <= len(start),
        "der_sequence_consumes_tail": der_length is not None and der_length == len(start),
        "full_pdf": full_info,
        "eof_prefix_pdf": core_info,
        "same_page_count": (full_info["pages"] == core_info["pages"]
                            if "pages" in full_info and "pages" in core_info else None),
        "same_extracted_text": full_text_hash == core_text_hash if comparable else None,
    }
    # Digests are internal only; the report compares them without exposing raw data.
    fingerprint = (hashlib.sha256(core).digest(), hashlib.sha256(tail).digest(), core_text_hash)
    return report, fingerprint


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


def inspect_route(opener, url, *, fingerprints=None):
    try:
        req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/pdf"})
        with opener.open(req, timeout=40) as resp:
            status = int(resp.status)
            if status != 200 or resp.geturl() != url:
                return {"status": status, "result": "unexpected_response"}
            raw = resp.read(MAX_PDF + 1)
            length = resp.headers.get("Content-Length", "")
            declared = int(length) if re.fullmatch(r"[0-9]{1,12}", length) else None
            report = {"status": status, "result": "inspected",
                      **inspect_body(raw, resp.headers.get("Content-Type", ""), declared)}
            tail_report, fingerprint = inspect_tail(raw)
            report["tail_analysis"] = tail_report
            if fingerprints is not None and fingerprint is not None:
                fingerprints.append(fingerprint)
            return report
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
    fingerprints = []
    for route, url in zip(("canonical", "alternative"), official_urls(identity), strict=True):
        report = inspect_route(opener, url, fingerprints=fingerprints)
        print("Dokument 7540 " + route + ": " + json.dumps(report, sort_keys=True))
    if len(fingerprints) == 2:
        left, right = fingerprints
        comparison = {"same_pdf_prefix_bytes": left[0] == right[0],
                      "same_tail_bytes": left[1] == right[1],
                      "same_prefix_extracted_text": left[2] == right[2] if left[2] and right[2] else None}
        print("Dokument 7540 sammenligning: " + json.dumps(comparison, sort_keys=True))
    print("Diagnose fullført; ingen endringer i D1, R2 eller oversettelseskø")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "diagnose"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    {"collect": collect, "diagnose": diagnose}[args.mode](args.folder)


if __name__ == "__main__":
    main()
