"""Private, exact-version CVM PDF mirror for the translation queue."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from urllib.parse import urlencode

from bemobi_cvm_rad import CANONICAL, DOWNLOAD, filing_identity, parse_rows
from bemobi_cvm_mirror import MAX_INDEX, MAX_PDF, _read
from bemobi_verified_mirror import PINNED_Q3_DOCUMENTS

PREFIX = "mirror/official/bemobi/translation/v1/"


def identity_key(identity) -> str:
    if not identity or len(identity) != 3 or not all(re.fullmatch(r"[0-9]{1,20}", x) for x in identity):
        raise ValueError("Ugyldig CVM-dokumentidentitet")
    return PREFIX + "-".join(identity)


def manifest_key(identity) -> str:
    return identity_key(identity) + "/manifest.json"


def pdf_key(identity, digest: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Ugyldig SHA-256")
    return identity_key(identity) + "/" + digest + ".pdf"


def official_urls(identity) -> tuple[str, str]:
    identity_key(identity)
    protocol, sequence, version = identity
    params = dict(CodigoInstituicao=1, descTipo="IPE", numProtocolo=protocol,
                  numSequencia=sequence, numVersao=version)
    return (CANONICAL + "?" + urlencode(dict(params, Tela="99")),
            DOWNLOAD + "?" + urlencode(dict(params, Tela="ext")))


def validate_listing(listing: dict, identity, delivery: str) -> None:
    """Require exactly the active, issuer-verified filing and delivery date."""
    day = date.fromisoformat(delivery)
    rows = parse_rows(listing, day, day)
    if not any(filing_identity(row["url"]) == identity and row["delivery"] == delivery
               for row in rows):
        raise ValueError("CVM-listen bekrefter ikke dokumentidentiteten")


def validate_manifest(manifest: dict, identity) -> dict:
    if (manifest.get("schema") != 1 or manifest.get("cvm_code") != "25500"
            or manifest.get("identity") != list(identity)):
        raise ValueError("CVM-reservens identitet stemmer ikke")
    validate_listing(manifest["listing"], identity, manifest["delivery"])
    artifact = manifest["artifact"]
    digest = artifact["sha256"]
    size = artifact["bytes"]
    if (artifact["url"] not in official_urls(identity)
            or artifact["key"] != pdf_key(identity, digest)
            or type(size) is not int or not 0 < size <= MAX_PDF):
        raise ValueError("CVM-reservens manifest er ugyldig")
    for spec in PINNED_Q3_DOCUMENTS.values():
        if filing_identity(spec["url"]) == identity and digest != spec["sha256"]:
            raise ValueError("CVM-reserven avviker fra tidligere verifisert SHA-256")
    return artifact


def verify_pdf(raw: bytes, artifact: dict) -> None:
    if (not raw.startswith(b"%PDF") or b"%%EOF" not in raw[-2048:]
            or len(raw) != artifact["bytes"] or len(raw) > MAX_PDF
            or hashlib.sha256(raw).hexdigest() != artifact["sha256"]):
        raise ValueError("CVM-reservens PDF består ikke integritetskontrollen")


async def read_translation_mirror(bucket, url: str, *, delivery: str | None = None) -> bytes:
    identity = filing_identity(url)
    manifest = json.loads(await _read(bucket, manifest_key(identity), MAX_INDEX))
    artifact = validate_manifest(manifest, identity)
    if delivery and manifest["delivery"] != delivery[:10]:
        raise ValueError("CVM-reservens publiseringsdato stemmer ikke")
    raw = await _read(bucket, artifact["key"], MAX_PDF)
    verify_pdf(raw, artifact)
    return raw
