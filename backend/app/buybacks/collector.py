from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from app.buybacks.euronext import ingest_euronext_buyback_status, parse_euronext_buyback_status
from app.db.connection import get_connection

EURONEXT_BASE = "https://live.euronext.com"
MFN_OTELLO_URL = "https://mfn.se/all/a/otello-corporation"
BUYBACK_TITLE = "OTEC: Otello Corporation share buyback program status"
EURONEXT_BUYBACK_SLUG = "otello-corporation-share-buyback-program-status"


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


def extract_page_text(html_text: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html_text)
    return extractor.text()


def discover_buyback_urls(html_text: str) -> list[str]:
    """Use MFN only to discover publication dates, then construct original Euronext URLs.

    No financial values are consumed from MFN. Every discovered date is verified by
    fetching and strictly parsing the corresponding Euronext/Oslo Bors message before
    anything is written to the database.
    """
    text = extract_page_text(html_text)
    pattern = re.compile(
        r"(20\d{2}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}\s+"
        + re.escape(BUYBACK_TITLE),
        re.I,
    )
    dates = sorted(set(pattern.findall(text)))
    return [
        f"{EURONEXT_BASE}/en/products/equities/company-news/{day}-{EURONEXT_BUYBACK_SLUG}"
        for day in dates
    ]


def _published_at_from_url(url: str) -> str:
    match = re.search(r"/company-news/(\d{4}-\d{2}-\d{2})-", url)
    if not match:
        raise ValueError(f"Fant ikke publiseringsdato i Euronext-URL: {url}")
    return f"{match.group(1)}T23:59:59Z"


def collect_recent_buybacks(
    database_path: str | None = None,
    *,
    company_url: str = MFN_OTELLO_URL,
) -> dict:
    """Discover status dates from MFN, but source and validate every value at Euronext.

    MFN is only a transient discovery index. The collector constructs the canonical
    Euronext URL for each date, fetches that original Oslo Bors/Newspoint message and
    fails closed if the Euronext text does not match the deterministic parser.
    """
    listing_html = _fetch(company_url)
    urls = discover_buyback_urls(listing_html)
    results: list[dict] = []
    errors: list[dict[str, str]] = []
    for url in urls:
        try:
            page_html = _fetch(url)
            text = extract_page_text(page_html)
            parse_euronext_buyback_status(text)
            result = ingest_euronext_buyback_status(
                text=text,
                url=url,
                published_at=_published_at_from_url(url),
                database_path=database_path,
            )
            results.append({"url": url, **result})
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)})
    return {
        "discovery_source": "MFN dates only",
        "financial_source": "Euronext / Oslo Bors Newspoint",
        "discovered": len(urls),
        "ingested": len(results),
        "results": results,
        "errors": errors,
    }


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
