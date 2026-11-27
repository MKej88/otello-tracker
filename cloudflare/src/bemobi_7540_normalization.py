"""Incident-specific, fail-closed treatment of CVM document 7540.

The official transport body is retained byte-for-byte. Only padding after EOF
may be removed in the private derivative used by the translation pipeline.
"""
from __future__ import annotations

import hashlib
import io
import json

from pypdf import PdfReader

from bemobi_cvm_rad import filing_identity
from bemobi_cvm_mirror import MAX_INDEX, MAX_PDF, _read
from bemobi_translation_mirror import identity_key, official_urls, validate_listing, verify_pdf
from bemobi_verified_mirror import PINNED_Q3_DOCUMENTS

DOCUMENT_ID = 7540
SCHEMA = "cvm-7540-padding-v1"
MAX_PADDING = 128 * 1024
PADDING = b"\x00\t\n\x0c\r "
# No pinned financial filing may be replaced by a derived copy.


def manifest_key_7540(identity):
    return identity_key(identity) + "/7540-normalization/manifest.json"


def object_key_7540(identity, digest, role):
    if role not in ("original", "processing"):
        raise ValueError("Ugyldig filrolle")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Ugyldig SHA-256")
    return identity_key(identity) + f"/7540-normalization/{digest}-{role}.pdf"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize_padding(raw):
    if not 0 < len(raw) <= MAX_PDF or not raw.startswith(b"%PDF-"):
        raise ValueError("Ugyldig PDF-original")
    eof = raw.rfind(b"%%EOF")
    if eof < 0:
        raise ValueError("PDF mangler sluttmarkør")
    core = raw[:eof + 5]
    tail = raw[eof + 5:]
    if not 2048 <= len(tail) <= MAX_PADDING or tail.strip(PADDING):
        raise ValueError("Kun bekreftet utfylling kan fjernes")
    if any(marker in core for marker in (b"/ByteRange", b"/Type /Sig", b"/SubFilter",
                                          b"\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x07\x02")):
        raise ValueError("Mulig digital signatur; normalisering avvises")
    normalized = core + b"\n"
    verify_pdf(normalized, {"bytes": len(normalized), "sha256": _sha(normalized)})
    return normalized


def _pdf_fingerprint(raw):
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 10:
        raise ValueError("Uventet PDF-struktur for dokument 7540")
    pages = [page.extract_text() or "" for page in reader.pages]
    if not any(text.strip() for text in pages):
        raise ValueError("PDF mangler lesbar tekst")
    return len(pages), _sha(json.dumps(pages, ensure_ascii=False).encode())


def verify_pair(original, normalized):
    if normalize_padding(original) != normalized:
        raise ValueError("Behandlingskopien avviker fra tillatt normalisering")
    original_info = _pdf_fingerprint(original)
    if original_info != _pdf_fingerprint(normalized):
        raise ValueError("Sideantall eller dokumenttekst avviker")
    return original_info


def make_manifest(identity, delivery, listing, original, normalized):
    pages, text_sha = verify_pair(original, normalized)
    def record(raw, role):
        digest = _sha(raw)
        return {"sha256": digest, "bytes": len(raw), "key": object_key_7540(identity, digest, role)}
    return {
        "schema": SCHEMA, "document_id": DOCUMENT_ID, "cvm_code": "25500",
        "identity": list(identity), "delivery": delivery, "listing": listing,
        "official_url": official_urls(identity)[1],
        "original": record(original, "original"), "processing": record(normalized, "processing"),
        "pages": pages, "page_text_sha256": text_sha,
    }


def validate_normalization_manifest(manifest, identity, delivery, document_id):
    if (document_id != DOCUMENT_ID or manifest.get("document_id") != DOCUMENT_ID
            or manifest.get("schema") != SCHEMA or manifest.get("cvm_code") != "25500"
            or manifest.get("identity") != list(identity) or manifest.get("delivery") != delivery
            or manifest.get("official_url") != official_urls(identity)[1]):
        raise ValueError("Normaliseringens identitet avviker")
    if any(filing_identity(spec["url"]) == identity for spec in PINNED_Q3_DOCUMENTS.values()):
        raise ValueError("Fastlåst original kan ikke normaliseres")
    validate_listing(manifest["listing"], identity, delivery)
    for role in ("original", "processing"):
        artifact = manifest[role]
        if (type(artifact.get("bytes")) is not int or not 0 < artifact["bytes"] <= MAX_PDF
                or artifact.get("key") != object_key_7540(identity, artifact["sha256"], role)):
            raise ValueError("Ugyldig normaliseringsmanifest")
    if not 2048 <= manifest["original"]["bytes"] - manifest["processing"]["bytes"] + 1 <= MAX_PADDING:
        raise ValueError("Ugyldig differanse i filstørrelse")
    return manifest


def verify_manifest_pair(manifest, original, processing):
    for role, raw in (("original", original), ("processing", processing)):
        spec = manifest[role]
        if len(raw) != spec["bytes"] or _sha(raw) != spec["sha256"]:
            raise ValueError("SHA-256 eller størrelse avviker")
    pages, text_sha = verify_pair(original, processing)
    if pages != manifest["pages"] or text_sha != manifest["page_text_sha256"]:
        raise ValueError("Dokumentets tekstkontroll avviker")
    return processing


async def read_7540_normalization(bucket, url, *, delivery, document_id):
    if document_id != DOCUMENT_ID or not delivery:
        raise ValueError("Normalisering er ikke autorisert for dokumentet")
    identity = filing_identity(url)
    manifest = json.loads(await _read(bucket, manifest_key_7540(identity), MAX_INDEX))
    validate_normalization_manifest(manifest, identity, delivery[:10], document_id)
    original = await _read(bucket, manifest["original"]["key"], MAX_PDF)
    processing = await _read(bucket, manifest["processing"]["key"], MAX_PDF)
    return verify_manifest_pair(manifest, original, processing)
