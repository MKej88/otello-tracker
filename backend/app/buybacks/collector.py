from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from app.buybacks.euronext import ingest_euronext_buyback_status, parse_euronext_buyback_status
from app.db.connection import get_connection

EURONEXT_BASE = "https://live.euronext.com"
OTEC_COMPANY_URL = f"{EURONEXT_BASE}/en/product/equities/NO0010040611-XOSL"
BUYBACK_PATH_MARKER = "otello-corporation-share-buyback-program-status"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return " ".join(self.parts)


def _fetch(url: str, timeout: int = 30) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "otello-tracker/0.6 (+private research)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def discover_buyback_urls(html_text: str, *, base_url: str = EURONEXT_BASE) -> list[str]:
    """Discover Euronext buyback status links visible in one OTEC company page."""
    candidates = re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.I)
    urls: set[str] = set()
    for raw in candidates:
        decoded = html.unescape(raw)
        if BUYBACK_PATH_MARKER not in decoded.lower():
            continue
        absolute = urljoin(base_url, decoded)
        if "/products/equities/company-news/" in absolute:
            urls.add(absolute.split("#", 1)[0])
    return sorted(urls)


def extract_page_text(html_text: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html_text)
    return extractor.text()


def _published_at_from_url(url: str) -> str:
    match = re.search(r"/company-news/(\d{4})-(\d{2})-(\d{2})-", url)
    if not match:
        raise ValueError(f"Fant ikke publiseringsdato i Euronext-URL: {url}")
    year, month, day = match.groups()
    return f"{year}-{month}-{day}T23:59:59+02:00"


def collect_recent_buybacks(
    database_path: str | None = None,
    *,
    company_url: str = OTEC_COMPANY_URL,
) -> dict:
    """Discover and ingest buyback messages currently linked from Euronext's OTEC page.

    The collector intentionally does not rely on a private/internal API. It parses only
    public company-news links. Repeated runs are idempotent through source-document and
    buyback uniqueness rules.
    """
    listing_html = _fetch(company_url)
    urls = discover_buyback_urls(listing_html)
    results: list[dict] = []
    errors: list[dict[str, str]] = []
    for url in urls:
        try:
            page_html = _fetch(url)
            text = extract_page_text(page_html)
            # Fail closed before touching the DB if the page no longer matches the schema.
            parse_euronext_buyback_status(text)
            result = ingest_euronext_buyback_status(
                text=text,
                url=url,
                published_at=_published_at_from_url(url),
                database_path=database_path,
            )
            results.append({"url": url, **result})
        except Exception as exc:  # surfaced to job status; no silent guessed data
            errors.append({"url": url, "error": str(exc)})
    return {"discovered": len(urls), "ingested": len(results), "results": results, "errors": errors}


def buyback_status(database_path: str | None = None) -> dict:
    with get_connection(database_path) as connection:
        aggregate = connection.execute(
            """
            SELECT COUNT(*) AS n, MIN(trade_date) AS min_date, MAX(trade_date) AS max_date,
                   SUM(shares) AS shares, SUM(CAST(amount_nok AS REAL)) AS amount_nok
            FROM buybacks
            """
        ).fetchone()
        latest = connection.execute(
            """
            SELECT trade_date, shares, avg_price_nok, amount_nok,
                   cumulative_program_shares, treasury_shares_after
            FROM buybacks ORDER BY trade_date DESC, id DESC LIMIT 1
            """
        ).fetchone()
        return {
            "status": "ok" if aggregate["n"] else "empty",
            "count": aggregate["n"],
            "from": aggregate["min_date"],
            "to": aggregate["max_date"],
            "shares_in_weekly_rows": aggregate["shares"],
            "amount_nok_in_weekly_rows": aggregate["amount_nok"],
            "latest": dict(latest) if latest is not None else None,
        }
