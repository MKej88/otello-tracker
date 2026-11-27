"""Read-only queue discovery, independent CVM validation and private R2 publication."""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloudflare" / "src"))
from pypdf import PdfReader
from bemobi_cvm_rad import PAGE, LIST, filing_identity
from bemobi_cvm_mirror import MAX_INDEX, MAX_PDF
from bemobi_translation_mirror import (official_urls, manifest_key, pdf_key,
                                       validate_listing, validate_manifest, verify_pdf)
from probe_bemobi_cvm_rad import HEADERS

MAX_DOCUMENTS = 12
QUEUE_SQL = """
SELECT sd.id AS document_id, sd.url, substr(sd.published_at,1,10) AS delivery
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code='CVM' AND sd.translation_status IN ('FAILED','PENDING')
  AND sd.translation_error IS NOT NULL
ORDER BY CASE WHEN sd.translation_attempts < 3 THEN 0 ELSE 1 END,
         sd.id DESC LIMIT 12
"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Uventet HTTP-omdirigering")


def bounded_read(response, maximum):
    raw = response.read(maximum + 1)
    if not raw or len(raw) > maximum:
        raise ValueError("Ugyldig responsstørrelse")
    return raw


def collect(folder):
    """The read-only token is never available to CVM or R2 subprocesses."""
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account):
        raise ValueError("Ugyldig kontoid")
    token = os.environ["CLOUDFLARE_READ_TOKEN"]
    root = "https://api.cloudflare.com/client/v4/accounts/" + account + "/d1/database"
    opener = urllib.request.build_opener(NoRedirect())
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    def api(url, data=None):
        req = urllib.request.Request(url, headers=headers, data=data)
        with opener.open(req, timeout=30) as resp:
            payload = json.loads(bounded_read(resp, MAX_INDEX))
        if payload.get("success") is not True:
            raise ValueError("D1-lesing mislyktes")
        return payload["result"]

    dbs = api(root + "?name=otello-nav&per_page=10")
    ids = [row["uuid"] for row in dbs if row.get("name") == "otello-nav"]
    if len(ids) != 1 or not re.fullmatch(r"[a-fA-F0-9-]{36}", ids[0]):
        raise ValueError("Fant ikke entydig D1-database")
    groups = api(root + "/" + ids[0] + "/query", json.dumps({"sql": QUEUE_SQL}).encode())
    if len(groups) != 1 or groups[0].get("success") is not True:
        raise ValueError("D1-køspørring mislyktes")
    rows = groups[0]["results"]
    if len(rows) > MAX_DOCUMENTS:
        raise ValueError("Køspørringen overskred grensen")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "queue.json").write_text(json.dumps(rows), encoding="utf-8")
    print("Dokumenter valgt for kontroll:", len(rows))


def get_listing(opener, delivery):
    day = date.fromisoformat(delivery).strftime("%d/%m/%Y")
    query = dict(dataDe=day, dataAte=day, empresa=",025500", setorAtividade="-1",
                 categoriaEmissor="-1", situacaoEmissor="-1", tipoParticipante="-1",
                 dataReferencia="", categoria="EST_-1,IPE_-1_-1_-1",
                 periodo="2", horaIni="", horaFim="", palavraChave="", ultimaDtRef="false",
                 tipoEmpresa="0", token="", versaoCaptcha="")
    req = urllib.request.Request(LIST, data=json.dumps(query).encode(), headers={
        **HEADERS, "Content-Type": "application/json; charset=utf-8",
        "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
    with opener.open(req, timeout=40) as resp:
        return json.loads(bounded_read(resp, MAX_INDEX))


class MirrorFailure(ValueError):
    """Fixed, non-sensitive stage codes for public workflow diagnostics."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def build_document(opener, row, listings):
    identity = filing_identity(row["url"])
    try:
        delivery = date.fromisoformat(row["delivery"]).isoformat()
    except (TypeError, ValueError) as exc:
        raise MirrorFailure("invalid_delivery_date") from exc
    if not identity:
        raise MirrorFailure("unsupported_filing_identity")
    if delivery not in listings:
        try:
            listings[delivery] = get_listing(opener, delivery)
        except urllib.error.HTTPError as exc:
            raise MirrorFailure(f"listing_http_{exc.code}") from exc
        except Exception as exc:
            raise MirrorFailure("listing_unavailable") from exc
    listing = listings[delivery]
    try:
        validate_listing(listing, identity, delivery)
    except (ValueError, KeyError, TypeError) as exc:
        raise MirrorFailure("listing_identity_or_date_not_verified") from exc
    failures = []
    canonical = None
    for index, url in enumerate(official_urls(identity)):
        stage = "download"
        try:
            request = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/pdf"})
            with opener.open(request, timeout=40) as resp:
                if resp.status != 200 or resp.geturl() != url:
                    raise ValueError("Uventet PDF-respons")
                raw = bounded_read(resp, MAX_PDF)
            if index == 0:
                canonical = raw
            digest = hashlib.sha256(raw).hexdigest()
            artifact = dict(url=url, bytes=len(raw), sha256=digest, key=pdf_key(identity, digest))
            manifest = dict(schema=1, cvm_code="25500", identity=list(identity),
                            delivery=delivery, listing=listing, artifact=artifact)
            stage = "manifest"
            verified = validate_manifest(manifest, identity)
            stage = "pdf_integrity"
            try:
                verify_pdf(raw, verified)
            except ValueError:
                if index != 1 or canonical is None:
                    raise
                from bemobi_cvm_padding_normalization import build_manifest
                stage = "padding_normalization"
                normalized_manifest, _ = build_manifest(identity, delivery, listing, canonical, raw)
                return normalized_manifest, raw
            stage = "pdf_readability"
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or not reader.pages:
                raise ValueError("PDF kan ikke leses")
            return manifest, raw
        except urllib.error.HTTPError as exc:
            failures.append(f"http_{exc.code}")
        except (ValueError, OSError, urllib.error.URLError) as exc:
            failures.append(stage + "_" + type(exc).__name__)
    raise MirrorFailure("official_routes_failed:" + ",".join(failures))


def build(folder):
    rows = json.loads((folder / "queue.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) > MAX_DOCUMENTS:
        raise ValueError("Ugyldig lokal kø")
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    listings = {}
    successes = failures = 0
    for row in rows:
        document_id = row.get("document_id")
        if type(document_id) is not int or document_id <= 0:
            raise ValueError("Ugyldig dokument-ID")
        try:
            manifest, raw = build_document(opener, row, listings)
            manifest_raw = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode()
            if len(manifest_raw) > MAX_INDEX:
                raise ValueError("Manifestet er for stort")
            out = folder / str(document_id)
            out.mkdir(exist_ok=False)
            write_local_pair(out, manifest, raw)
            (out / "manifest.json").write_bytes(manifest_raw)
            successes += 1
            print(f"Dokument {document_id}: verifisert original" + (" og behandlingskopi" if manifest["schema"] == 2 else ""))
        except Exception as exc:
            failures += 1
            detail = exc.code if isinstance(exc, MirrorFailure) else type(exc).__name__
            print(f"Dokument {document_id}: ikke verifisert ({detail})")
    print(f"Verifisert: {successes}; uavklart: {failures}")
    if rows and not successes:
        raise SystemExit("Ingen dokumenter kunne verifiseres; eksisterende R2-kopier er bevart")


def write_local_pair(out, manifest, raw):
    if manifest.get("schema") == 2:
        from bemobi_7540_normalization import normalize_padding
        from bemobi_cvm_padding_normalization import verify_manifest_pair
        processing = normalize_padding(raw)
        verify_manifest_pair(manifest, raw, processing)
        (out / "processing.pdf").write_bytes(processing)
    (out / "original.pdf").write_bytes(raw)


def verify_local_pair(out, manifest, identity, delivery, *, prefix=""):
    if manifest["delivery"] != delivery:
        raise ValueError("Publiseringsdato avviker")
    with (out / (prefix + "original.pdf")).open("rb") as handle:
        raw = bounded_read(handle, MAX_PDF)
    if manifest.get("schema") == 2:
        from bemobi_cvm_padding_normalization import validate_manifest as validate_padding, verify_manifest_pair
        validate_padding(manifest, identity, delivery)
        with (out / (prefix + "processing.pdf")).open("rb") as handle:
            processing = bounded_read(handle, MAX_PDF)
        verify_manifest_pair(manifest, raw, processing)
        return [(manifest["original"]["key"], "original.pdf", "application/pdf"),
                (manifest["processing"]["key"], "processing.pdf", "application/pdf")]
    artifact = validate_manifest(manifest, identity)
    verify_pdf(raw, artifact)
    return [(artifact["key"], "original.pdf", "application/pdf")]


def publish(folder):
    bucket = os.environ["CLOUDFLARE_R2_BUCKET_NAME"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", bucket):
        raise ValueError("Ugyldig R2-bucket")
    wrangler = ROOT / "cloudflare" / "node_modules" / ".bin" / "wrangler"
    directories = sorted(p for p in folder.iterdir() if p.is_dir() and p.name.isdigit())
    if len(directories) > MAX_DOCUMENTS:
        raise ValueError("For mange lokale dokumenter")
    for out in directories:
        with (out / "manifest.json").open("rb") as handle:
            manifest = json.loads(bounded_read(handle, MAX_INDEX))
        identity = tuple(manifest["identity"])
        artifacts = verify_local_pair(out, manifest, identity, manifest["delivery"])
        # Publish immutable original/processing first; manifest is the commit marker.
        for key, filename, content_type in [*artifacts, (manifest_key(identity), "manifest.json", "application/json")]:
            local = out / filename
            readback = out / ("readback-" + filename)
            target = bucket + "/" + key
            subprocess.run([str(wrangler), "r2", "object", "put", target,
                            "--file=" + str(local), "--content-type=" + content_type, "--remote"], check=True)
            subprocess.run([str(wrangler), "r2", "object", "get", target,
                            "--file=" + str(readback), "--remote"], check=True)
            if local.read_bytes() != readback.read_bytes():
                raise ValueError("R2-tilbakelesing avviker")
        print(f"Dokument {out.name}: PDF og manifest verifisert i R2")
    print("Publiserte dokumenter:", len(directories))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "build", "publish"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    {"collect": collect, "build": build, "publish": publish}[args.mode](args.folder)


if __name__ == "__main__":
    main()
