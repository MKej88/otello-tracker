"""SHA-256-pinned copies of two already independently verified official CVM PDFs.

Only used after the normal issuer/CVM HTTPS downloads fail with HTTP 526.
R2 is a private transport cache, not a new financial-data source.
"""
from __future__ import annotations

import hashlib

# Independently downloaded from official CVM on a GitHub runner on 20 Nov 2026.
# Never update these hashes or provenance without reviewing the actual filings.
Q3_RELEASE_URL = (
    "https://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx"
    "?CodigoInstituicao=1&Tela=99&descTipo=IPE"
    "&numProtocolo=1588745&numSequencia=1113451&numVersao=1"
)
Q3_JCP_URL = (
    "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx"
    "?CodigoInstituicao=1&Tela=ext&descTipo=IPE"
    "&numProtocolo=1588756&numSequencia=1113462&numVersao=1"
)

PINNED_Q3_DOCUMENTS = {
    "result": {
        "url": Q3_RELEASE_URL,
        "sha256": "c65b40a695030bc8ba35b68970fcbe6a1d05828ed5ff5a7bfe327714f94cb661",
        "size": 18291776,
        "max_bytes": 24 * 1024 * 1024,
        "key": (
            "mirror/official/bemobi/3q26/"
            "cvm-result-c65b40a695030bc8ba35b68970fcbe6a1d05828ed5ff5a7bfe327714f94cb661.pdf"
        ),
    },
    "jcp": {
        "url": Q3_JCP_URL,
        "sha256": "11e9b67b4711459c1f0f32636170ca24bc4b2478a748c3a83b7e4b6a654b5bbf",
        "size": None,
        "max_bytes": 2 * 1024 * 1024,
        "key": (
            "mirror/official/bemobi/3q26/"
            "cvm-jcp-11e9b67b4711459c1f0f32636170ca24bc4b2478a748c3a83b7e4b6a654b5bbf.pdf"
        ),
    },
}


async def read_verified_q3_document(bucket, kind: str) -> tuple[bytes, str]:
    """Read private R2 bytes, then verify the exact official document digest.

    The caller must independently verify the filing's issuer, quarter and
    publication date before accepting a transport fallback.
    """
    if kind not in PINNED_Q3_DOCUMENTS:
        raise ValueError("Unknown pinned Bemobi document")
    if bucket is None:
        raise RuntimeError("Verified official PDF mirror unavailable: no private R2 bucket")
    document = PINNED_Q3_DOCUMENTS[kind]
    stored = await bucket.get(document["key"])
    if stored is None:
        raise RuntimeError("Verified official PDF mirror unavailable: pinned object missing")
    if int(getattr(stored, "size", 0) or 0) > document["max_bytes"]:
        raise ValueError("Verified official PDF mirror exceeds byte limit")
    payload = bytes(await stored.arrayBuffer())
    if (
        not payload.startswith(b"%PDF")
        or len(payload) > document["max_bytes"]
        or (document["size"] is not None and len(payload) != document["size"])
        or hashlib.sha256(payload).hexdigest() != document["sha256"]
    ):
        raise ValueError("Verified official PDF mirror SHA-256/length mismatch")
    return payload, str(document["url"])
