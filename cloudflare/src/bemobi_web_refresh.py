from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse

try:
    from .bounded_response import read_response_bytes
    from .r2_archive import archive_bytes
except ImportError:
    from bounded_response import read_response_bytes
    from r2_archive import archive_bytes

BEMOBI_OWNERSHIP_URL = "https://ri.bemobi.com.br/governanca/composicao-acionaria/"
BEMOBI_ANALYST_URL = "https://ri.bemobi.com.br/nossas-acoes/cobertura-de-analistas-2/"
BEMOBI_CALENDAR_URL = "https://ri.bemobi.com.br/nossas-acoes/calendario-de-eventos/"
MARKETSCREENER_FINANCES_URL = (
    "https://www.marketscreener.com/quote/stock/"
    "BEMOBI-MOBILE-TECH-S-A-119084218/finances/"
)
XP_BMOB3_REPORTS_URL = "https://conteudos.xpi.com.br/acoes/bmob3/relatorios/"

MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_RESULT_BYTES = 12 * 1024 * 1024
USER_AGENT = "otello-tracker/1.0 private-investor-dashboard"


class _HTMLFactsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.links: list[tuple[str, str]] = []
        self.meta: dict[str, str] = {}
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._anchor_href: str | None = None
        self._anchor_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_map = {str(k).lower(): str(v) for k, v in attrs if v is not None}
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag == "a":
            self._anchor_href = attrs_map.get("href")
            self._anchor_text = []
        elif tag == "meta":
            key = attrs_map.get("property") or attrs_map.get("name")
            value = attrs_map.get("content")
            if key and value:
                self.meta[key.lower()] = value

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        if self._anchor_text is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(_clean(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None
            self._cell = None
        elif tag == "a" and self._anchor_text is not None:
            if self._anchor_href:
                self.links.append((self._anchor_href, _clean(" ".join(self._anchor_text))))
            self._anchor_href = None
            self._anchor_text = None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _decode_html(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Kunne ikke dekode HTML-kilde")


def _html_parser(html: str) -> _HTMLFactsParser:
    parser = _HTMLFactsParser()
    parser.feed(html)
    parser.close()
    return parser


def _number(value: str, *, million_scale: bool = False) -> float:
    raw = _clean(value).upper().replace("R$", "").replace("%", "").replace(" ", "")
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    suffix = raw[-1:] if raw[-1:] in {"K", "M", "B"} else ""
    if suffix:
        raw = raw[:-1]
    raw = re.sub(r"[^0-9,.-]", "", raw)
    if not raw or raw in {"-", ".", ","}:
        raise ValueError(f"Ugyldig tall: {value!r}")

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        left, right = raw.rsplit(",", 1)
        raw = left.replace(",", "") + ("." + right if len(right) <= 2 else right)
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif "." in raw:
        left, right = raw.rsplit(".", 1)
        if len(right) == 3 and len(left) >= 1:
            raw = left + right

    result = float(raw)
    if negative:
        result = -result
    if suffix == "B" and million_scale:
        result *= 1000
    elif suffix == "K" and million_scale:
        result /= 1000
    return result


def _percentage(value: str) -> float:
    raw = _clean(value).replace("%", "").replace(" ", "")
    raw = re.sub(r"[^0-9,.-]", "", raw)
    if not raw or raw in {"-", ".", ","}:
        raise ValueError(f"Ugyldig prosent: {value!r}")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    return float(raw)


def _integer(value: str) -> int:
    digits = re.sub(r"\D", "", value)
    if not digits:
        raise ValueError(f"Ugyldig heltall: {value!r}")
    return int(digits)


def _parse_ir_date(value: str) -> str | None:
    raw = _clean(value).lower().replace(".", "")
    month_names = {
        "jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4,
        "mai": 5, "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
        "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
    }
    match = re.search(r"(\d{1,2})[-/ ]([a-z]{3})[-/ ](\d{2,4})", raw)
    if match:
        day = int(match.group(1))
        month = month_names.get(match.group(2))
        year = int(match.group(3))
        if year < 100:
            year += 2000
        if month:
            return date(year, month, day).isoformat()
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if match:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
    return None


def _rating(value: str) -> str:
    norm = _clean(value).lower()
    if any(token in norm for token in ("compra", "buy", "outperform", "overweight")):
        return "BUY"
    if any(token in norm for token in ("manuten", "neutro", "neutral", "hold", "equal-weight")):
        return "HOLD"
    if any(token in norm for token in ("venda", "sell", "underperform", "underweight")):
        return "SELL"
    return "OTHER"


def parse_ownership_html(html: str, *, checked_date: str) -> dict[str, Any]:
    rows = _html_parser(html).rows
    otello = next((row for row in rows if row and "otello technology" in row[0].lower()), None)
    total = next((row for row in rows if row and row[0].strip().lower() in {"total", "total geral"}), None)
    if otello is None or total is None or len(otello) < 3 or len(total) < 2:
        raise ValueError("Bemobi IR eiertabell har ukjent struktur")
    shares = _integer(otello[1])
    ownership_pct = _percentage(otello[2])
    total_shares = _integer(total[1])
    implied = shares / total_shares * 100
    if not (10_000_000 <= shares <= total_shares <= 250_000_000):
        raise ValueError("Bemobi IR eiertall er utenfor forventet område")
    if abs(implied - ownership_pct) > 0.15:
        raise ValueError("Bemobi IR eierandel stemmer ikke med aksjetall")
    return {
        "shares": shares,
        "ownership_pct": round(ownership_pct, 6),
        "bemobi_total_shares": total_shares,
        "checked_date": checked_date,
        "quality": "OFFICIAL_IR_AUTO",
    }


def parse_analyst_coverage_html(html: str) -> list[dict[str, Any]]:
    rows = _html_parser(html).rows
    result: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 5 or "institui" in row[0].lower() or "institution" in row[0].lower():
            continue
        target_cell = row[-1]
        if "R$" not in target_cell and not re.search(r"\d+[,.]\d+", target_cell):
            continue
        last_update = _parse_ir_date(row[-2])
        if last_update is None:
            continue
        target = _number(target_cell)
        if not (1 <= target <= 200):
            continue
        analyst = {
            "institution": _clean(row[0]),
            "analyst": _clean(row[1]),
            "rating": _rating(row[-3]),
            "target_price_brl": round(target, 4),
            "last_update": last_update,
        }
        if analyst["institution"] and analyst["rating"] != "OTHER":
            result.append(analyst)
    if len(result) < 2:
        raise ValueError("Bemobi IR analytikertabell ga for få gyldige rader")
    institutions = [item["institution"] for item in result]
    if len(set(institutions)) != len(institutions):
        raise ValueError("Bemobi IR analytikertabell inneholder duplikater")
    return result


def _metric_key(label: str) -> str | None:
    norm = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    aliases = {
        "revenue_mbrl": ("net sales", "sales", "revenue", "turnover"),
        "ebitda_mbrl": ("ebitda",),
        "ebit_mbrl": ("ebit", "operating profit"),
        "net_income_mbrl": ("net income", "net profit"),
        "eps_brl": ("eps", "earnings per share"),
        "net_debt_mbrl": ("net debt", "net cash"),
    }
    for key, names in aliases.items():
        if any(norm == name or norm.startswith(name + " ") for name in names):
            return key
    return None


def parse_marketscreener_finances_html(html: str) -> list[dict[str, Any]]:
    rows = _html_parser(html).rows
    year_positions: dict[int, int] = {}
    for row in rows:
        positions = {
            int(cell): idx
            for idx, cell in enumerate(row)
            if re.fullmatch(r"20\d{2}", _clean(cell)) and 2025 <= int(cell) <= 2030
        }
        if 2026 in positions and 2027 in positions and len(positions) >= 2:
            year_positions = positions
            break
    if not year_positions:
        raise ValueError("MarketScreener årskolonner ikke funnet")

    metrics: dict[str, dict[int, float]] = {}
    for row in rows:
        if not row:
            continue
        key = _metric_key(row[0])
        if key is None:
            continue
        values: dict[int, float] = {}
        for year, idx in year_positions.items():
            if idx >= len(row):
                continue
            try:
                values[year] = _number(row[idx], million_scale=key != "eps_brl")
            except ValueError:
                pass
        if values:
            metrics.setdefault(key, {}).update(values)

    required = {"revenue_mbrl", "ebitda_mbrl", "ebit_mbrl", "net_income_mbrl", "eps_brl", "net_debt_mbrl"}
    years: list[dict[str, Any]] = []
    for year in (2026, 2027):
        if not all(year in metrics.get(key, {}) for key in required):
            raise ValueError(f"MarketScreener mangler komplett konsensus for {year}")
        payload = {"year": year, **{key: metrics[key][year] for key in required}}
        if not (0 < payload["revenue_mbrl"] < 10_000 and 0 < payload["ebitda_mbrl"] < payload["revenue_mbrl"]):
            raise ValueError(f"MarketScreener {year} har ulogiske estimater")
        if not (-5_000 < payload["net_debt_mbrl"] < 5_000 and 0 < payload["eps_brl"] < 100):
            raise ValueError(f"MarketScreener {year} har estimater utenfor kontrollgrenser")
        years.append(payload)
    return years


def _period_from_text(text: str) -> str | None:
    match = re.search(r"\b([1-4])\s*[TQ]\s*([2-9]\d)\b", text, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1)}Q{match.group(2)}"


def _period_end(period: str) -> str:
    quarter = int(period[0])
    year = 2000 + int(period[-2:])
    return {1: date(year, 3, 31), 2: date(year, 6, 30), 3: date(year, 9, 30), 4: date(year, 12, 31)}[quarter].isoformat()


def _next_period(period: str) -> str:
    quarter = int(period[0])
    year = 2000 + int(period[-2:])
    if quarter == 4:
        quarter, year = 1, year + 1
    else:
        quarter += 1
    return f"{quarter}Q{str(year)[-2:]}"


def _extract_metric(text: str, labels: tuple[str, ...], *, percent: bool = False) -> float | None:
    for label in labels:
        match = re.search(label + r".{0,100}?(-?\d{1,4}(?:[\.,]\d{1,2})?)\s*(%?)", text, re.IGNORECASE | re.DOTALL)
        if match:
            try:
                value = _number(match.group(1))
            except ValueError:
                continue
            if percent and match.group(2) != "%":
                continue
            return value
    return None


def parse_bemobi_result_text(text: str, *, published_date: str) -> dict[str, Any]:
    normalized = _clean(text)
    if "bemobi" not in normalized.lower():
        raise ValueError("Resultatdokument mangler Bemobi-signatur")
    period = _period_from_text(normalized)
    if period is None:
        raise ValueError("Fant ikke kvartalsperiode i Bemobi-resultat")

    revenue = _extract_metric(normalized, (r"Receita L[ií]quida(?: Ajustada)?", r"Net Revenue"))
    ebitda = _extract_metric(normalized, (r"EBITDA Ajustad[oa]", r"Adjusted EBITDA"))
    net_income = _extract_metric(normalized, (r"Lucro L[ií]quido Ajustad[oa]", r"Adjusted Net Income"))
    cash_generation = _extract_metric(
        normalized,
        (r"EBITDA Ajustad[oa]\s*[-–]\s*Capex", r"Adjusted EBITDA\s*[-–]\s*Capex"),
    )
    if None in {revenue, ebitda, net_income, cash_generation}:
        raise ValueError("Bemobi-resultatet mangler ett eller flere obligatoriske nøkkeltall")
    assert revenue is not None and ebitda is not None and net_income is not None and cash_generation is not None
    if not (50 < revenue < 2_000 and 0 < ebitda < revenue and -500 < net_income < 1_000 and 0 <= cash_generation <= ebitda * 1.5):
        raise ValueError("Bemobi-resultatet har nøkkeltall utenfor kontrollgrenser")

    margin = _extract_metric(normalized, (r"Margem EBITDA Ajustad[oa]", r"Adjusted EBITDA Margin"), percent=True)
    cash_conversion = _extract_metric(normalized, (r"Cash Conversion", r"Convers[aã]o de Caixa"), percent=True)
    cash = _extract_metric(normalized, (r"Posi[cç][aã]o de Caixa", r"Caixa e Equivalentes", r"Cash Position"))
    return {
        "period": period,
        "period_end": _period_end(period),
        "published_date": published_date,
        "adjusted_net_revenue_mbrl": round(revenue, 4),
        "adjusted_ebitda_mbrl": round(ebitda, 4),
        "adjusted_net_income_mbrl": round(net_income, 4),
        "ebitda_less_capex_mbrl": round(cash_generation, 4),
        "adjusted_ebitda_margin_pct": None if margin is None else round(margin, 4),
        "cash_conversion_pct": None if cash_conversion is None else round(cash_conversion, 4),
        "cash_mbrl": None if cash is None else round(cash, 4),
        "quality": "OFFICIAL_RESULT_AUTO",
    }


def parse_xp_preview_html(html: str) -> dict[str, Any] | None:
    parser = _html_parser(html)
    text = _clean(re.sub(r"<[^>]+>", " ", html))
    period = _period_from_text(text)
    if period is None or not any(token in text.lower() for token in ("prévia", "previa", "preview")):
        return None
    ebitda = _extract_metric(text, (r"EBITDA ajustad[oa]", r"adjusted EBITDA"))
    net_income = _extract_metric(text, (r"lucro l[ií]quido ajustad[oa]", r"adjusted net income"))
    revenue = _extract_metric(text, (r"receita l[ií]quida", r"net revenue"))
    if ebitda is None or net_income is None:
        return None
    published = parser.meta.get("article:published_time") or parser.meta.get("date")
    published_date = str(published)[:10] if published and re.match(r"20\d{2}-\d{2}-\d{2}", str(published)) else None
    estimates = [
        {"metric": "adjusted_ebitda_mbrl", "label": "Justert EBITDA", "value_mbrl": round(ebitda, 4)},
        {"metric": "adjusted_net_income_mbrl", "label": "Justert resultat", "value_mbrl": round(net_income, 4)},
    ]
    if revenue is not None:
        estimates.insert(0, {"metric": "adjusted_net_revenue_mbrl", "label": "Nettoomsetning", "value_mbrl": round(revenue, 4)})
    return {"period": period, "published_date": published_date, "estimates": estimates}


async def _fetch_bytes(
    url: str,
    *,
    label: str,
    max_bytes: int,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
    accept: str = "text/html,application/xhtml+xml,*/*;q=0.8",
) -> bytes:
    if fetcher is None:
        from workers import fetch
        fetcher = fetch
    response = await fetcher(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    status = int(getattr(response, "status", 0) or 0)
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"{label} feilet med HTTP {status or 'unknown'}")
    return await read_response_bytes(response, max_bytes=max_bytes, label=label)


async def _store_web_document(
    repository,
    archive_bucket,
    *,
    source_code: str,
    url: str,
    kind: str,
    title: str,
    target_date: str,
    payload: bytes,
) -> int:
    digest = hashlib.sha256(payload).hexdigest()
    archived = None
    if archive_bucket is not None:
        archived = await archive_bytes(
            archive_bucket,
            payload,
            source=source_code.lower(),
            kind=kind,
            logical_date=target_date,
            filename=f"{kind}-{digest[:12]}.html",
        )
    return await repository.create_source_document(
        source_code=source_code,
        external_id=f"web:{kind}:{digest[:24]}",
        document_type="WEB_SOURCE_SNAPSHOT",
        title=title,
        url=url,
        published_at=f"{target_date}T00:00:00Z",
        content_sha256=digest,
        metadata={
            "workflow": "cloudflare_full_refresh",
            "parser": "bemobi-web-v1",
            "r2_key": archived.get("r2_key") if archived else None,
        },
    )


async def _upsert_fact(
    repository,
    *,
    fact_type: str,
    fact_key: str,
    as_of_date: str | None,
    published_date: str | None,
    payload: dict[str, Any],
    source_name: str,
    source_url: str,
    source_document_id: int | None,
    quality: str,
    notes: str,
) -> None:
    await repository.run(
        """
        INSERT INTO bemobi_investor_facts(
            fact_type, fact_key, as_of_date, published_date, payload_json,
            source_name, source_url, quality, notes, source_document_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fact_type, fact_key) DO UPDATE SET
            as_of_date=excluded.as_of_date,
            published_date=excluded.published_date,
            payload_json=excluded.payload_json,
            source_name=excluded.source_name,
            source_url=excluded.source_url,
            quality=excluded.quality,
            notes=excluded.notes,
            source_document_id=excluded.source_document_id,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            fact_type, fact_key, as_of_date, published_date,
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            source_name, source_url, quality, notes, source_document_id,
        ),
    )


async def _sync_holding(repository, payload: dict[str, Any], document_id: int, target_date: str) -> int:
    current = await repository.first(
        """
        SELECT id, shares, ownership_pct, effective_from
        FROM bemobi_holdings
        WHERE effective_to IS NULL
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """
    )
    shares = int(payload["shares"])
    pct = str(payload["ownership_pct"])
    if current is not None and int(current["shares"]) == shares:
        await repository.run(
            "UPDATE bemobi_holdings SET ownership_pct=?, source_document_id=?, notes=? WHERE id=?",
            (pct, document_id, "Automatisk kontrollert mot Bemobi IR.", current["id"]),
        )
        return 0
    if current is not None:
        close_date = (date.fromisoformat(target_date) - timedelta(days=1)).isoformat()
        if close_date >= str(current["effective_from"]):
            await repository.run("UPDATE bemobi_holdings SET effective_to=? WHERE id=?", (close_date, current["id"]))
    await repository.run(
        """
        INSERT INTO bemobi_holdings(
            effective_from, effective_to, shares, ownership_pct, source_document_id, notes
        ) VALUES (?, NULL, ?, ?, ?, ?)
        """,
        (target_date, shares, pct, document_id, "Automatisk oppdatert fra Bemobi IR."),
    )
    return 1


async def sync_bemobi_ir(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    ownership_raw = await _fetch_bytes(BEMOBI_OWNERSHIP_URL, label="Bemobi IR ownership", max_bytes=MAX_HTML_BYTES, fetcher=fetcher)
    ownership = parse_ownership_html(_decode_html(ownership_raw), checked_date=target_date)
    ownership_doc = await _store_web_document(
        repository, archive_bucket, source_code="BEMOBI_IR", url=BEMOBI_OWNERSHIP_URL,
        kind="ownership", title="Bemobi ownership structure", target_date=target_date, payload=ownership_raw,
    )
    await _upsert_fact(
        repository,
        fact_type="OWNERSHIP", fact_key="current", as_of_date=target_date, published_date=None,
        payload=ownership, source_name="Bemobi IR", source_url=BEMOBI_OWNERSHIP_URL,
        source_document_id=ownership_doc, quality="OFFICIAL_IR_AUTO",
        notes="Automatisk kontrollert mot Bemobis offisielle aksjonærside.",
    )
    holding_changes = await _sync_holding(repository, ownership, ownership_doc, target_date)

    analyst_raw = await _fetch_bytes(BEMOBI_ANALYST_URL, label="Bemobi IR analyst coverage", max_bytes=MAX_HTML_BYTES, fetcher=fetcher)
    analysts = parse_analyst_coverage_html(_decode_html(analyst_raw))
    analyst_doc = await _store_web_document(
        repository, archive_bucket, source_code="BEMOBI_IR", url=BEMOBI_ANALYST_URL,
        kind="analyst-coverage", title="Bemobi analyst coverage", target_date=target_date, payload=analyst_raw,
    )
    names = [item["institution"] for item in analysts]
    placeholders = ",".join("?" for _ in names)
    await repository.run(
        f"DELETE FROM bemobi_investor_facts WHERE fact_type='ANALYST' AND fact_key NOT IN ({placeholders})",
        tuple(names),
    )
    for analyst in analysts:
        await _upsert_fact(
            repository,
            fact_type="ANALYST", fact_key=analyst["institution"], as_of_date=target_date,
            published_date=analyst["last_update"], payload=analyst, source_name="Bemobi IR",
            source_url=BEMOBI_ANALYST_URL, source_document_id=analyst_doc,
            quality="OFFICIAL_IR_AUTO", notes="Automatisk hentet fra Bemobi IR analytikerdekning.",
        )
    return {
        "status": "ok",
        "ownership": ownership,
        "analyst_count": len(analysts),
        "holding_changes": holding_changes,
        "rows_written": 1 + len(analysts) + holding_changes,
    }


async def sync_marketscreener_consensus(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    try:
        raw = await _fetch_bytes(
            MARKETSCREENER_FINANCES_URL, label="MarketScreener Bemobi finances",
            max_bytes=MAX_HTML_BYTES, fetcher=fetcher,
        )
        years = parse_marketscreener_finances_html(_decode_html(raw))
    except Exception as exc:
        return {"status": "not_available", "error": str(exc)[:700], "rows_written": 0}
    document_id = await _store_web_document(
        repository, archive_bucket, source_code="MARKETSCREENER", url=MARKETSCREENER_FINANCES_URL,
        kind="forward-consensus", title="Bemobi MarketScreener finances", target_date=target_date, payload=raw,
    )
    for item in years:
        await _upsert_fact(
            repository, fact_type="FORWARD_CONSENSUS", fact_key=str(item["year"]),
            as_of_date=target_date, published_date=None, payload=item, source_name="MarketScreener",
            source_url=MARKETSCREENER_FINANCES_URL, source_document_id=document_id,
            quality="PUBLIC_AGGREGATE_AUTO",
            notes="Automatisk hentet offentlig aggregert konsensus; siste gode data beholdes ved kildefeil.",
        )
    return {"status": "ok", "years": [item["year"] for item in years], "rows_written": len(years)}


def _pdf_text(payload: bytes) -> str:
    candidate = payload
    if not candidate.startswith(b"%PDF"):
        try:
            with zipfile.ZipFile(io.BytesIO(candidate)) as archive:
                names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
                if names:
                    candidate = archive.read(names[0])
        except zipfile.BadZipFile:
            pass
    if not candidate.startswith(b"%PDF"):
        raise ValueError("Kilden returnerte ikke PDF/ZIP med PDF")
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(candidate))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


async def sync_latest_result_release(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    candidates = await repository.all(
        """
        SELECT sd.id, sd.url, sd.title, sd.published_at, s.code AS source_code
        FROM company_news cn
        JOIN instruments i ON i.id=cn.issuer_instrument_id
        JOIN source_documents sd ON sd.id=cn.source_document_id
        JOIN sources s ON s.id=sd.source_id
        WHERE i.symbol='BMOB3' AND cn.category='RESULTS' AND sd.url IS NOT NULL
        ORDER BY COALESCE(cn.published_at, sd.published_at) DESC, cn.id DESC
        LIMIT 6
        """
    )
    if not candidates:
        return {"status": "skipped", "reason": "no_cvm_result_document", "rows_written": 0}

    errors: list[str] = []
    for candidate in candidates:
        already = await repository.first(
            "SELECT id FROM bemobi_investor_facts WHERE fact_type='RESULT' AND source_document_id=? LIMIT 1",
            (candidate["id"],),
        )
        if already is not None:
            return {"status": "skipped", "reason": "latest_result_already_ingested", "rows_written": 0}
        try:
            raw = await _fetch_bytes(
                str(candidate["url"]), label="Bemobi result release", max_bytes=MAX_RESULT_BYTES,
                fetcher=fetcher, accept="application/pdf,application/zip,application/octet-stream,*/*;q=0.8",
            )
            text = _pdf_text(raw)
            published_date = str(candidate.get("published_at") or target_date)[:10]
            result = parse_bemobi_result_text(text, published_date=published_date)
        except Exception as exc:
            errors.append(f"{candidate.get('title')}: {exc}")
            continue

        period = result["period"]
        if archive_bucket is not None:
            await archive_bytes(
                archive_bucket, raw, source=str(candidate.get("source_code") or "cvm").lower(),
                kind="bemobi-result-release", logical_date=published_date,
                filename=f"bemobi-{period.lower()}-{hashlib.sha256(raw).hexdigest()[:12]}.pdf",
            )
        await repository.run(
            "UPDATE source_documents SET content_sha256=COALESCE(content_sha256, ?) WHERE id=?",
            (hashlib.sha256(raw).hexdigest(), candidate["id"]),
        )
        await _upsert_fact(
            repository, fact_type="RESULT", fact_key=period, as_of_date=result["period_end"],
            published_date=published_date, payload=result, source_name=str(candidate.get("source_code") or "CVM"),
            source_url=str(candidate["url"]), source_document_id=int(candidate["id"]),
            quality="OFFICIAL_RESULT_AUTO", notes="Automatisk parsede nøkkeltall fra offentlig Bemobi-resultatdokument.",
        )
        ttm = {
            "period": period,
            "adjusted_net_income_mbrl": result["adjusted_net_income_mbrl"],
            "adjusted_ebitda_mbrl": result["adjusted_ebitda_mbrl"],
            "adjusted_cash_generation_mbrl": result["ebitda_less_capex_mbrl"],
            "source": str(candidate.get("source_code") or "CVM"),
            "source_url": str(candidate["url"]),
        }
        await _upsert_fact(
            repository, fact_type="TTM_QUARTER", fact_key=period, as_of_date=result["period_end"],
            published_date=published_date, payload=ttm, source_name=str(candidate.get("source_code") or "CVM"),
            source_url=str(candidate["url"]), source_document_id=int(candidate["id"]),
            quality="OFFICIAL_RESULT_AUTO", notes="Automatisk oppdatert TTM-kvartal fra offentlig resultatdokument.",
        )

        previous = await repository.first(
            """
            SELECT fact_key, payload_json FROM bemobi_investor_facts
            WHERE fact_type='NEXT_QUARTER' AND fact_key=? LIMIT 1
            """,
            (period,),
        )
        beat_rows = 0
        if previous is not None:
            previous_payload = json.loads(str(previous.get("payload_json") or "{}"))
            estimates = previous_payload.get("estimates") or []
            metrics = []
            actual_by_metric = {
                "adjusted_net_revenue_mbrl": result["adjusted_net_revenue_mbrl"],
                "adjusted_ebitda_mbrl": result["adjusted_ebitda_mbrl"],
                "adjusted_net_income_mbrl": result["adjusted_net_income_mbrl"],
            }
            for estimate in estimates:
                metric = str(estimate.get("metric") or "")
                if metric in actual_by_metric and estimate.get("value_mbrl") is not None:
                    metrics.append({
                        "metric": metric,
                        "label": estimate.get("label") or metric,
                        "estimate": estimate["value_mbrl"],
                        "actual": actual_by_metric[metric],
                    })
            if metrics:
                await _upsert_fact(
                    repository, fact_type="BEAT_MISS", fact_key=period, as_of_date=result["period_end"],
                    published_date=published_date,
                    payload={"period": period, "broker": "XP", "published_date": published_date, "metrics": metrics},
                    source_name="XP + Bemobi/CVM", source_url=str(candidate["url"]),
                    source_document_id=int(candidate["id"]), quality="AUTO_PREVIEW_VS_RESULT",
                    notes="Automatisk sammenligning av lagret offentlig forhåndsestimat mot rapportert resultat.",
                )
                beat_rows = 1

        next_period = _next_period(period)
        await _upsert_fact(
            repository, fact_type="NEXT_QUARTER", fact_key=next_period, as_of_date=target_date,
            published_date=None,
            payload={
                "period": next_period, "report_date": None, "date_quality": "NOT_CONFIRMED",
                "label": "Dato ikke bekreftet av Bemobi", "status": "WAITING_FOR_PUBLIC_ESTIMATES",
                "estimates": [],
                "tracked_metrics": ["Nettoomsetning", "Justert EBITDA", "EBITDA-margin", "Justert resultat", "EPS"],
                "note": "Opprettet automatisk etter siste rapport; rapportdato/estimater fylles fra offentlige kilder når de blir tilgjengelige.",
            },
            source_name="Bemobi IR", source_url=BEMOBI_CALENDAR_URL, source_document_id=None,
            quality="NOT_CONFIRMED", notes="Neste kvartal rulles automatisk etter nytt resultat.",
        )
        return {"status": "ok", "period": period, "next_period": next_period, "rows_written": 3 + beat_rows}

    return {"status": "not_available", "reason": "result_documents_not_parseable", "errors": errors[:6], "rows_written": 0}


async def sync_xp_preview(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    latest = await repository.first(
        """
        SELECT fact_key, payload_json FROM bemobi_investor_facts
        WHERE fact_type='NEXT_QUARTER'
        ORDER BY COALESCE(as_of_date, published_date, '') DESC, id DESC LIMIT 1
        """
    )
    if latest is None:
        return {"status": "skipped", "reason": "next_quarter_not_initialized", "rows_written": 0}
    expected_period = str(latest["fact_key"])
    try:
        index_raw = await _fetch_bytes(XP_BMOB3_REPORTS_URL, label="XP BMOB3 reports", max_bytes=MAX_HTML_BYTES, fetcher=fetcher)
        parser = _html_parser(_decode_html(index_raw))
        candidates = []
        for href, label in parser.links:
            absolute = urljoin(XP_BMOB3_REPORTS_URL, href)
            haystack = f"{absolute} {label}".lower()
            if "xpi.com.br" in urlparse(absolute).netloc and "bmob3" in haystack and any(token in haystack for token in ("previa", "prévia", "preview")):
                candidates.append(absolute)
        for url in list(dict.fromkeys(candidates))[:8]:
            raw = await _fetch_bytes(url, label="XP Bemobi preview", max_bytes=MAX_HTML_BYTES, fetcher=fetcher)
            preview = parse_xp_preview_html(_decode_html(raw))
            if preview is None or preview["period"] != expected_period:
                continue
            document_id = await _store_web_document(
                repository, archive_bucket, source_code="XP", url=url, kind="bemobi-preview",
                title=f"XP Bemobi preview {expected_period}", target_date=target_date, payload=raw,
            )
            existing = json.loads(str(latest.get("payload_json") or "{}"))
            updated = {
                **existing,
                "period": expected_period,
                "status": "PUBLIC_ESTIMATES_AVAILABLE",
                "estimates": [
                    {**item, "broker": "XP", "source_url": url, "published_date": preview.get("published_date")}
                    for item in preview["estimates"]
                ],
                "note": "Offentlig XP-forhåndsestimat hentet automatisk; ikke markedskonsensus.",
            }
            await _upsert_fact(
                repository, fact_type="NEXT_QUARTER", fact_key=expected_period, as_of_date=target_date,
                published_date=preview.get("published_date"), payload=updated, source_name="XP",
                source_url=url, source_document_id=document_id, quality="PUBLIC_BROKER_PREVIEW_AUTO",
                notes="Automatisk hentet offentlig XP-preview uten innlogging eller betalingsmur.",
            )
            return {"status": "ok", "period": expected_period, "rows_written": 1, "source_url": url}
        return {"status": "not_available", "reason": "no_public_preview_for_next_quarter", "rows_written": 0}
    except Exception as exc:
        return {"status": "not_available", "error": str(exc)[:700], "rows_written": 0}


async def refresh_bemobi_web(
    repository,
    *,
    target_date: str,
    archive_bucket=None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh current Bemobi investor facts without destroying last-good data on source drift.

    Official IR ownership/analyst coverage is the critical path. Result documents are taken
    from the already-discovered CVM result feed. MarketScreener and XP are best-effort
    secondary sources; failures there degrade the result but do not remove existing facts.
    """
    ir = await sync_bemobi_ir(
        repository, target_date=target_date, archive_bucket=archive_bucket, fetcher=fetcher
    )
    result = await sync_latest_result_release(
        repository, target_date=target_date, archive_bucket=archive_bucket, fetcher=fetcher
    )
    consensus = await sync_marketscreener_consensus(
        repository, target_date=target_date, archive_bucket=archive_bucket, fetcher=fetcher
    )
    xp = await sync_xp_preview(
        repository, target_date=target_date, archive_bucket=archive_bucket, fetcher=fetcher
    )
    secondary = [result, consensus, xp]
    degraded = any(item.get("status") == "not_available" for item in secondary)
    rows_written = sum(int(item.get("rows_written") or 0) for item in [ir, *secondary])
    return {
        "status": "partial" if degraded else "ok",
        "rows_written": rows_written,
        "ir": ir,
        "result_release": result,
        "consensus": consensus,
        "xp_preview": xp,
        "policy": "official-first-last-good-preserved",
    }
