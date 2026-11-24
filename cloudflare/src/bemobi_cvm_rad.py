"""Live public CVM RAD discovery for BMOB3; read-only network, no financial writes."""
from __future__ import annotations

import asyncio
import html
import json
import re
import unicodedata
import urllib.parse
from datetime import date, timedelta
from bounded_response import read_response_text

PAGE = "https://www.rad.cvm.gov.br/ENETWeb/frmConsultaExternaCVM.aspx?codigoCVM=25500"
LIST = PAGE.split("?")[0] + "/ListarDocumentos"
DOWNLOAD = "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx"
CANONICAL = "https://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx"
LIMIT = 3 * 1024 * 1024

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


def filing_identity(url):
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname != "www.rad.cvm.gov.br":
        return None
    if parsed.path not in ("/ENET/frmDownloadDocumento.aspx", "/ENETCONSULTA/frmDownloadDocumento.aspx"):
        return None
    params = urllib.parse.parse_qs(parsed.query)
    if params.get("CodigoInstituicao") != ["1"] or params.get("descTipo") != ["IPE"]:
        return None
    values = [params.get(k, []) for k in ("numProtocolo", "numSequencia", "numVersao")]
    if any(len(v) != 1 or not v[0].isdigit() for v in values):
        return None
    return tuple(v[0] for v in values)


def release_candidates(rows):
    """Only actual quarterly earnings releases, not ITR, presentations or notices."""
    releases = {}
    for row in rows:
        identity = filing_identity(row["url"])
        if row["kind"] != "RELEASE" or not identity:
            continue
        title = norm(row["title"])
        match = re.search(r"\b([1-4])[tq]\s*(\d{2})\b", title)
        if not match or "press-release" not in title:
            continue
        quarter = f"{match[1]}Q{match[2]}"
        protocol, sequence, version = identity
        # A revised release must remain eligible; collapse exact duplicate rows.
        key = (protocol, sequence)
        previous = releases.get(key)
        if previous and int(previous["version"]) >= int(version):
            continue
        url = CANONICAL + "?" + urllib.parse.urlencode(dict(
            CodigoInstituicao=1, Tela=99, descTipo="IPE",
            numProtocolo=protocol, numSequencia=sequence, numVersao=version))
        releases[key] = {**row, "url": url, "expected_period": quarter}
    return sorted(releases.values(), key=lambda row: (row["delivery"], row["expected_period"][-2:],
        row["expected_period"][0], int(row["protocol"]), int(row["version"])), reverse=True)[:3]


async def discover_live_releases(*, target_date, fetcher=None):
    """Bound a public request; a failure never erases the existing sources."""
    end = date.fromisoformat(target_date)
    start = end - timedelta(days=120)
    try:
        if fetcher is None:
            from workers import fetch
            fetcher = fetch
        payload = dict(dataDe=start.strftime("%d/%m/%Y"), dataAte=end.strftime("%d/%m/%Y"),
            empresa=",025500", setorAtividade="-1", categoriaEmissor="-1", situacaoEmissor="-1",
            tipoParticipante="-1", dataReferencia="", categoria="EST_-1,IPE_-1_-1_-1",
            periodo="2", horaIni="", horaFim="", palavraChave="", ultimaDtRef="false",
            tipoEmpresa="0", token="", versaoCaptcha="")
        async def request():
            response = await fetcher(LIST, method="POST", headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                "Referer": PAGE}, body=json.dumps(payload))
            if not getattr(response, "ok", False):
                raise RuntimeError(f"CVM RAD HTTP {getattr(response, 'status', 'unknown')}")
            return json.loads(await read_response_text(response, max_bytes=LIMIT, label="CVM RAD"))
        raw = await asyncio.wait_for(request(), timeout=35)
        rows = parse_rows(raw, start, end)
        releases = release_candidates(rows)
        return releases, {"status": "ok" if releases else "empty",
            "checked_date": target_date, "active_documents": len(rows),
            "release_count": len(releases),
            "latest_period": releases[0]["expected_period"] if releases else None}
    except Exception as exc:
        return [], {"status": "not_available", "checked_date": target_date,
                    "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
