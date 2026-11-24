"""Build a bounded, independently validated latest CVM release mirror locally."""
from __future__ import annotations
import hashlib
import http.cookiejar
import json
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare" / "src"))
from bemobi_cvm_rad import PAGE, LIST, parse_rows, release_candidates, filing_identity
from bemobi_cvm_mirror import pdf_key, MAX_PDF, MAX_INDEX, validate_index
from bemobi_web_refresh import _pdf_text, parse_bemobi_result_text
from bemobi_verified_mirror import PINNED_Q3_DOCUMENTS
from probe_bemobi_cvm_rad import read

def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(UTC)
    end = observed.date()
    start = end - timedelta(days=120)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    read(opener, PAGE)
    query = dict(dataDe=start.strftime("%d/%m/%Y"), dataAte=end.strftime("%d/%m/%Y"),
        empresa=",025500", setorAtividade="-1", categoriaEmissor="-1", situacaoEmissor="-1",
        tipoParticipante="-1", dataReferencia="", categoria="EST_-1,IPE_-1_-1_-1",
        periodo="2", horaIni="", horaFim="", palavraChave="", ultimaDtRef="false",
        tipoEmpresa="0", token="", versaoCaptcha="")
    listing = json.loads(read(opener, LIST, data=json.dumps(query).encode(), limit=MAX_INDEX))
    releases = release_candidates(parse_rows(listing, start, end))
    if not releases:
        raise SystemExit("No current earnings release; preserve previous R2 index")
    latest = releases[0]
    raw = read(opener, latest["url"], limit=MAX_PDF)
    if not raw.startswith(b"%PDF"):
        raise SystemExit("CVM response not a PDF")
    parsed = parse_bemobi_result_text(_pdf_text(raw), published_date=latest["delivery"])
    if parsed["period"] != latest["expected_period"]:
        raise SystemExit("CVM title and PDF quarter mismatch")
    digest = hashlib.sha256(raw).hexdigest()
    identity = filing_identity(latest["url"])
    if identity == ("1588745", "1113451", "1") and digest != PINNED_Q3_DOCUMENTS["result"]["sha256"]:
        raise SystemExit("Previously verified Q3 original differs; manual review required")
    artifact = dict(url=latest["url"], period=parsed["period"], sha256=digest,
                    bytes=len(raw), key=pdf_key(identity, digest))
    index = dict(schema=1, cvm_code="25500", observed_at=observed.isoformat(),
                 start_date=start.isoformat(), end_date=end.isoformat(), listing=listing, artifact=artifact)
    validate_index(index, target_date=end.isoformat())
    index_raw = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode()
    if len(index_raw) > MAX_INDEX:
        raise SystemExit("Index exceeds limit")
    (out / "release.pdf").write_bytes(raw)
    (out / "latest.json").write_bytes(index_raw)
    (out / "key.txt").write_text(artifact["key"], encoding="utf-8")
    print("Verified CVM", parsed["period"], "filing", identity, "bytes", len(raw), "SHA256", digest)

if __name__ == "__main__":
    main()
