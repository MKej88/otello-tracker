"""Download two immutable, independently verified official Bemobi CVM PDFs.

Run on a GitHub-hosted runner (not in Cloudflare Workers). All bytes are
verified before they may be uploaded to private R2. No source rewrite,
unverified document, or financial value is accepted.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloudflare" / "src"))

from bemobi_verified_mirror import PINNED_Q3_DOCUMENTS  # noqa: E402
from bemobi_web_refresh import _pdf_text, parse_bemobi_result_text  # noqa: E402
from bemobi_distribution_ingestion import parse_official_distribution  # noqa: E402


def fetch_verified_official(kind: str) -> bytes:
    spec = PINNED_Q3_DOCUMENTS[kind]
    request = Request(
        spec["url"],
        headers={"User-Agent": "OtelloTracker-source-verification/1.0",
                 "Accept": "application/pdf,application/octet-stream"},
    )
    with urlopen(request, timeout=90) as response:
        final = urlsplit(response.geturl())
        if final.scheme != "https" or final.hostname != "www.rad.cvm.gov.br":
            raise ValueError("CVM redirect to unexpected origin")
        if response.status != 200:
            raise RuntimeError("Official CVM PDF download returned non-200")
        payload = response.read(spec["max_bytes"] + 1)
    if (
        not payload.startswith(b"%PDF")
        or not payload.endswith(b"%%EOF") and b"%%EOF" not in payload[-2048:]
        or len(payload) > spec["max_bytes"]
        or (spec["size"] is not None and len(payload) != spec["size"])
        or hashlib.sha256(payload).hexdigest() != spec["sha256"]
    ):
        raise ValueError("CVM PDF does not match pinned SHA-256 and size")
    return payload


def verify_financial_content(kind: str, payload: bytes) -> None:
    text = _pdf_text(payload)
    if kind == "result":
        parsed = parse_bemobi_result_text(text, published_date="2026-11-12")
        if parsed["period"] != "3Q26":
            raise ValueError("CVM document is not the 3Q26 earnings release")
        cash = parsed.get("cash_mbrl")
        if cash is None or not 318 <= float(cash) <= 320:
            raise ValueError("3Q26 release lacks the published R$319m cash")
    elif kind == "jcp":
        parsed = parse_official_distribution(text, published_date="2026-11-12")
        expected = {
            "action_type": "JCP",
            "announcement_date": "2026-11-12",
            "record_date": "2026-11-17",
            "ex_date": "2026-11-18",
            "payment_date": "2026-11-30",
            "gross_amount_per_share": "0.19178292",
            "net_amount_per_share": "0.15822091",
        }
        for key, value in expected.items():
            if str(parsed.get(key)) != value:
                raise ValueError(f"Official CVM JCP: {key} differs")
    else:
        raise ValueError("Unknown official document kind")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for kind in ("result", "jcp"):
        payload = fetch_verified_official(kind)
        verify_financial_content(kind, payload)
        path = folder / f"{kind}.pdf"
        path.write_bytes(payload)
        print(
            "VERIFIED_CVM", kind, "bytes=", len(payload),
            "sha256=", hashlib.sha256(payload).hexdigest(),
            "r2_key=", PINNED_Q3_DOCUMENTS[kind]["key"],
        )


if __name__ == "__main__":
    main()
