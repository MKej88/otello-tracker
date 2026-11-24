"""Read-only public CVM RAD/ENET discovery acceptance probe (no credentials)."""
from __future__ import annotations

import hashlib
import html
import http.cookiejar
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, timedelta

PAGE = "https://www.rad.cvm.gov.br/ENETWeb/frmConsultaExternaCVM.aspx?codigoCVM=25500"
LIST = PAGE.split("?")[0] + "/ListarDocumentos"
DOWNLOAD = "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx"
LIMIT = 3 * 1024 * 1024
PDF_LIMIT = 24 * 1024 * 1024
HEADERS = {"User-Agent": "OtelloTracker CVM public document verification/1.0", "Referer": PAGE}

def clean(value):
    return " ".join(re.sub(r"<[^>]*>", "", html.unescape(value)).split())

def norm(value):
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()

def parse_rows(payload, start, end):
    result = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or result.get("temErro") or not isinstance(result.get("dados"), str):
        raise ValueError("Unexpected CVM listing response or upstream error")
    rows = []
    for line in result["dados"].split("&*"):
        if not line.strip():
            continue
        fields = line.split("$&")
        if len(fields) < 11:
            raise ValueError("Unexpected CVM row structure")
        if norm(clean(fields[7])) != "ativo":
            continue
        issuer = " ".join(clean(x) for x in fields[:2])
        if "bemobi" not in norm(issuer) and not re.search(r"\b0*25500\b", issuer):
            raise ValueError("Issuer could not be independently identified in CVM row")
        params = re.search(r"OpenDownloadDocumentos\('(\d+)','(\d+)','(\d+)','([A-Za-z0-9_-]+)'\)", fields[10])
        if not params:
            continue
        seq, version, protocol, desc = params.groups()
        delivered = re.search(r"(\d{2})/(\d{2})/(\d{4})", clean(fields[6]))
        if not delivered:
            raise ValueError("CVM delivery date missing")
        day, month, year = map(int, delivered.groups())
        delivery = date(year, month, day)
        if not start <= delivery <= end:
            raise ValueError("CVM delivery outside requested interval")
        title = " | ".join(clean(x) for x in fields[2:5] + fields[11:12] if clean(x))
        normalized = norm(title)
        if re.search(r"apresenta[cç][aã]o|presentation", normalized):
            kind = "PRESENTATION"
        elif re.search(r"release|relatorio de resultados|earnings release", normalized):
            kind = "RELEASE"
        elif re.search(r"juros sobre capital|interest on equity|\bjcp\b", normalized):
            kind = "JCP"
        elif re.search(r"\bitr\b|informacoes trimestrais", normalized):
            kind = "ITR"
        else:
            kind = "OTHER"
        url = DOWNLOAD + "?" + urllib.parse.urlencode(dict(Tela="ext", descTipo=desc,
            CodigoInstituicao=1, numProtocolo=protocol, numSequencia=seq, numVersao=version))
        rows.append(dict(protocol=protocol, sequence=seq, version=version, kind=kind,
                         title=title[:250], delivery=delivery.isoformat(), url=url))
    return rows

def read(opener, url, *, data=None, limit=LIMIT):
    request = urllib.request.Request(url, data=data, headers={**HEADERS,
        "Accept": "application/json,*/*", "Content-Type": "application/json; charset=utf-8",
        "X-Requested-With": "XMLHttpRequest"})
    with opener.open(request, timeout=40) as response:
        if urllib.parse.urlsplit(response.geturl()).hostname != "www.rad.cvm.gov.br":
            raise ValueError("Unexpected final source host")
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("CVM response exceeds bounded read limit")
        return raw

def discover(opener, start, end):
    payload = dict(dataDe=start.strftime("%d/%m/%Y"), dataAte=end.strftime("%d/%m/%Y"),
        empresa=",025500", setorAtividade="-1", categoriaEmissor="-1", situacaoEmissor="-1",
        tipoParticipante="-1", dataReferencia="", categoria="EST_-1,IPE_-1_-1_-1",
        periodo="2", horaIni="", horaFim="", palavraChave="", ultimaDtRef="false",
        tipoEmpresa="0", token="", versaoCaptcha="")
    return parse_rows(json.loads(read(opener, LIST, data=json.dumps(payload).encode())), start, end)

def main():
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    read(opener, PAGE)
    historical = discover(opener, date(2026, 11, 12), date(2026, 11, 13))
    today = date.today()
    recent = discover(opener, today - timedelta(days=14), today)
    for label, rows in (("historical", historical), ("recent", recent)):
        print(label, "active rows", len(rows))
        for row in rows[:60]:
            print(json.dumps(row, ensure_ascii=False))
    # Protocols below are acceptance assertions only, never discovery inputs.
    release = [r for r in historical if r["protocol"] == "1588745" and r["sequence"] == "1113451" and r["kind"] == "RELEASE"]
    jcp = [r for r in historical if r["protocol"] == "1588756" and r["sequence"] == "1113462"]
    if not release or not jcp:
        raise SystemExit("Acceptance failed: known Q3 release/JCP not independently discovered")
    latest = max(release, key=lambda r: int(r["version"]))
    raw = read(opener, latest["url"], limit=PDF_LIMIT)
    digest = hashlib.sha256(raw).hexdigest()
    if not raw.startswith(b"%PDF"):
        raise SystemExit("Discovered release did not return PDF")
    print("Q3 release PDF bytes", len(raw), "SHA256", digest, "version", latest["version"])
    if latest["version"] != "1" or digest != "c65b40a695030bc8ba35b68970fcbe6a1d05828ed5ff5a7bfe327714f94cb661":
        raise SystemExit("Release differs from verified Q3 original; review required")
    print("PASS: independently discovered and downloaded verified official Q3 release")

if __name__ == "__main__":
    main()
