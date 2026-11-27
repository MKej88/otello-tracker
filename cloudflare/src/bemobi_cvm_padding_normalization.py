"""Conservative, independently verified CVM padding derivatives for translation only.

The original alternative-route response remains immutable in R2. Both official
routes must have the same PDF prefix. No financial source or NAV is modified.
"""
from __future__ import annotations

import hashlib
import io
import json
import re

from pypdf import PdfReader
from bemobi_7540_normalization import normalize_padding, verify_pair, MAX_PADDING
from bemobi_cvm_rad import filing_identity
from bemobi_cvm_mirror import MAX_PDF
from bemobi_translation_mirror import identity_key, official_urls, validate_listing
from bemobi_verified_mirror import PINNED_Q3_DOCUMENTS

SCHEMA = 2
POLICY = "cvm-identical-prefix-padding-v1"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def key(identity, sha, role):
    if role not in ("original", "processing") or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("Ugyldig normaliseringsnøkkel")
    return identity_key(identity) + "/padding-v1/" + sha + "-" + role + ".pdf"


def reject_signature(raw):
    # Fail closed for interactive forms, signature references or permissions.
    if re.search(rb"/(?:ByteRange|Sig|SubFilter|AcroForm|Perms)(?=[\s/<>\[\]()]|$)", raw):
        raise ValueError("Mulig signatur eller skjema")
    reader = PdfReader(io.BytesIO(raw), strict=True)
    root = reader.trailer["/Root"]
    if any(k in root for k in ("/AcroForm", "/Perms")):
        raise ValueError("Mulig signatur eller skjema")


def verify_pair_strict(original, processing):
    reject_signature(original)
    reject_signature(processing)
    return verify_pair(original, processing)


def build_manifest(identity, delivery, listing, canonical, original):
    validate_listing(listing, identity, delivery)
    if any(filing_identity(spec["url"]) == identity for spec in PINNED_Q3_DOCUMENTS.values()):
        raise ValueError("Fastlåst original kan ikke normaliseres")
    processing = normalize_padding(original)
    eof = canonical.rfind(b"%%EOF")
    if (not 0 < len(canonical) <= MAX_PDF or eof < 0
            or canonical[:eof+5] + b"\n" != processing):
        raise ValueError("Offisielle PDF-prefikser er ikke identiske")
    reject_signature(canonical)
    # Compare canonical pages/text too, without accepting its trailing data.
    from bemobi_7540_normalization import _pdf_fingerprint
    pages, text_sha = verify_pair_strict(original, processing)
    if _pdf_fingerprint(canonical) != (pages, text_sha):
        raise ValueError("Ordinær kilde avviker i sideantall eller tekst")
    def record(raw, role):
        sha = digest(raw)
        return {"sha256": sha, "bytes": len(raw), "key": key(identity, sha, role)}
    manifest = {
        "schema": SCHEMA, "policy": POLICY, "cvm_code": "25500",
        "identity": list(identity), "delivery": delivery, "listing": listing,
        "official_url": official_urls(identity)[1],
        "canonical_url": official_urls(identity)[0],
        "canonical_prefix_sha256": digest(processing),
        "original": record(original,"original"),
        "processing": record(processing,"processing"),
        "pages": pages, "page_text_sha256": text_sha,
    }
    validate_manifest(manifest, identity, delivery)
    return manifest, processing


def validate_manifest(manifest, identity, delivery):
    if (not identity or manifest.get("schema") != SCHEMA or manifest.get("policy") != POLICY
            or manifest.get("cvm_code") != "25500" or manifest.get("identity") != list(identity)
            or not delivery or manifest.get("delivery") != delivery
            or manifest.get("official_url") != official_urls(identity)[1]
            or manifest.get("canonical_url") != official_urls(identity)[0]):
        raise ValueError("Normaliseringens identitet avviker")
    if any(filing_identity(spec["url"]) == identity for spec in PINNED_Q3_DOCUMENTS.values()):
        raise ValueError("Fastlåst original kan ikke normaliseres")
    validate_listing(manifest["listing"], identity, delivery)
    for role in ("original","processing"):
        artifact = manifest[role]
        if (type(artifact.get("bytes")) is not int or not 0 < artifact["bytes"] <= MAX_PDF
                or artifact.get("key") != key(identity, artifact["sha256"], role)):
            raise ValueError("Ugyldig filmanifest")
    if (manifest["canonical_prefix_sha256"] != manifest["processing"]["sha256"]
            or not 2048 <= manifest["original"]["bytes"] - manifest["processing"]["bytes"] + 1 <= MAX_PADDING
            or type(manifest.get("pages")) is not int or not 1 <= manifest["pages"] <= 10
            or not re.fullmatch(r"[a-f0-9]{64}", manifest["page_text_sha256"])):
        raise ValueError("Ugyldig normaliseringsmetadata")
    return manifest


def verify_manifest_pair(manifest, original, processing):
    for role, raw in (("original",original),("processing",processing)):
        spec = manifest[role]
        if len(raw) != spec["bytes"] or digest(raw) != spec["sha256"]:
            raise ValueError("SHA-256 eller størrelse avviker")
    pages, text_sha = verify_pair_strict(original, processing)
    if (pages, text_sha) != (manifest["pages"], manifest["page_text_sha256"]):
        raise ValueError("Tekstkontroll avviker")
    return processing
