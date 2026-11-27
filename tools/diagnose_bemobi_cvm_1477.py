"""Read-only transport investigation of historical CVM document 1477."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import urllib.request
from datetime import date
from pathlib import Path

from diagnose_bemobi_cvm_7540 import SQL, inspect_route
from reactivate_bemobi_translation_documents import d1_client
from mirror_bemobi_translation_queue import NoRedirect, get_listing
from bemobi_cvm_rad import filing_identity
from bemobi_translation_mirror import official_urls, validate_listing

DOCUMENT_ID = 1477


def collect(folder):
    rows = d1_client("CLOUDFLARE_READ_TOKEN")(SQL, (DOCUMENT_ID,))["results"]
    if len(rows) != 1 or rows[0]["document_id"] != DOCUMENT_ID:
        raise ValueError("Fant ikke entydig CVM-dokument 1477")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "filing.json").write_text(json.dumps(rows[0]), encoding="utf-8")
    print("Dokument 1477: kildeidentitet hentet (kun lesing)")


def diagnose(folder):
    row = json.loads((folder / "filing.json").read_text(encoding="utf-8"))
    if row.get("document_id") != DOCUMENT_ID:
        raise ValueError("Uventet dokument-ID")
    identity = filing_identity(row["url"])
    delivery = date.fromisoformat(row["delivery"]).isoformat()
    if not identity:
        raise ValueError("Ugyldig CVM-identitet")
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    validate_listing(get_listing(opener, delivery), identity, delivery)
    print("Dokument 1477: aktivt dokument, utsteder og dato bekreftet")
    fingerprints = []
    for route, url in zip(("canonical", "alternative"), official_urls(identity), strict=True):
        result = inspect_route(opener, url, fingerprints=fingerprints)
        print("Dokument 1477 " + route + ": " + json.dumps(result, sort_keys=True))
    if len(fingerprints) == 2:
        left, right = fingerprints
        print("Dokument 1477 sammenligning: " + json.dumps({
            "same_pdf_prefix_bytes": left[0] == right[0],
            "same_tail_bytes": left[1] == right[1],
            "same_prefix_extracted_text": left[2] == right[2] if left[2] and right[2] else None,
        }, sort_keys=True))
    print("Diagnose fullført; ingen endringer i D1, R2 eller oversettelseskø")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "diagnose"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    {"collect": collect, "diagnose": diagnose}[args.mode](args.folder)
