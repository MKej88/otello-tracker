from __future__ import annotations

import html
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.buybacks.coverage import buyback_coverage_gaps
from app.buybacks.euronext import (
    ingest_euronext_buyback_status,
    parse_euronext_buyback_status,
)
from app.buybacks.official_backfill import seed_known_official_buybacks
from app.db.connection import get_connection

EURONEXT_BASE = "https://live.euronext.com"
MFN_BASE = "https://mfn.se"
MFN_OTELLO_URL = f"{MFN_BASE}/all/a/otello-corporation"
MFN_BUYBACK_MARKER = "otec-otello-corporation-share-buyback-program-status"
EURONEXT_BUYBACK_SLUG = "otello-corporation-share-buyback-program-status"
OSLO_TZ = ZoneInfo("Europe/Oslo")
MAX_HTML_BYTES = 3 * 1024 * 1024


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
        payload = response.read(MAX_HTML_BYTES + 1)
    if len(payload) > MAX_HTML_BYTES:
        raise ValueError("MFN-respons overstiger sikker størrelsesgrense")
    if not payload.strip():
        raise ValueError("MFN returnerte en tom respons")
    return payload.decode("utf-8", errors="replace")


def extract_page_text(html_text: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html_text)
    return extractor.text()


def discover_buyback_urls(html_text: str) -> list[str]:
    """Discover public MFN mirror article URLs; no financial fields are read here."""
    candidates = re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.I)
    urls: set[str] = set()
    for raw in candidates:
        decoded = html.unescape(raw)
        if MFN_BUYBACK_MARKER not in decoded.lower():
            continue
        urls.add(urljoin(MFN_BASE, decoded).split("#", 1)[0].split("?", 1)[0])
    return sorted(urls)


def _publication_timestamp(text: str) -> str:
    match = re.search(r"(20\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", text)
    if not match:
        raise ValueError("Fant ikke publiseringstidspunkt i MFN-mirror")
    local = datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}").replace(
        tzinfo=OSLO_TZ
    )
    return local.isoformat()


def _canonical_euronext_url(text: str) -> str:
    match = re.search(r"(20\d{2}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}", text)
    if not match:
        raise ValueError("Fant ikke publiseringsdato for Euronext canonical URL")
    return (
        f"{EURONEXT_BASE}/en/products/equities/company-news/"
        f"{match.group(1)}-{EURONEXT_BUYBACK_SLUG}"
    )


def _assert_oslo_bors_mirror(text: str) -> None:
    normalized = " ".join(text.split())
    if not re.search(r"(?:Källa|Source)\s+Oslo\s+Børs", normalized, re.I):
        raise ValueError(
            "MFN-artikkelen er ikke merket med Oslo Børs som upstream-kilde"
        )


def _latest_reported_cash_anchor(database_path: str | None = None) -> str | None:
    with get_connection(database_path) as connection:
        row = connection.execute(
            "SELECT MAX(as_of_date) AS max_date FROM cash_anchors WHERE anchor_type = 'REPORTED'"
        ).fetchone()
        return row["max_date"]


def collect_recent_buybacks(
    database_path: str | None = None,
    *,
    company_url: str = MFN_OTELLO_URL,
) -> dict:
    """Ingest strict Oslo Bors buyback releases from a labelled public mirror.

    MFN is stored explicitly as a non-official mirror with Oslo Bors upstream metadata.
    A tiny curated official backfill closes known mirror-feed omissions. Cumulative values
    validate both historical gaps and, separately, completeness after the latest reported
    cash anchor used by the live NAV forecast.
    """
    listing_html = _fetch(company_url)
    urls = discover_buyback_urls(listing_html)
    results: list[dict] = []
    errors: list[dict[str, str]] = []
    for mirror_url in urls:
        try:
            page_html = _fetch(mirror_url)
            text = extract_page_text(page_html)
            _assert_oslo_bors_mirror(text)
            parse_euronext_buyback_status(text)
            canonical_url = _canonical_euronext_url(text)
            result = ingest_euronext_buyback_status(
                text=text,
                url=mirror_url,
                published_at=_publication_timestamp(text),
                database_path=database_path,
                source_code="MFN",
                source_metadata={
                    "source_quality": "MIRROR",
                    "upstream_source": "Oslo Bors",
                    "upstream_provider": "Oslo Bors Newspoint",
                    "canonical_euronext_url": canonical_url,
                    "financial_fields_require_strict_parser": True,
                },
            )
            results.append(
                {"mirror_url": mirror_url, "canonical_url": canonical_url, **result}
            )
        except Exception as exc:
            errors.append({"url": mirror_url, "error": str(exc)})

    official_backfill = seed_known_official_buybacks(database_path)
    latest_anchor = _latest_reported_cash_anchor(database_path)
    historical_gaps = buyback_coverage_gaps(database_path)
    current_gaps = (
        buyback_coverage_gaps(database_path, since_date=latest_anchor)
        if latest_anchor is not None
        else historical_gaps
    )
    return {
        "discovery_source": "MFN public Otello feed",
        "stored_source": "MFN mirror + explicit curated Euronext gaps",
        "upstream_source": "Oslo Bors",
        "discovered": len(urls),
        "ingested": len(results),
        "official_backfill": official_backfill,
        "latest_reported_cash_anchor": latest_anchor,
        "historical_coverage_complete": not historical_gaps,
        "historical_coverage_gaps": historical_gaps,
        "current_coverage_complete": not current_gaps,
        "current_coverage_gaps": current_gaps,
        "results": results,
        "errors": errors,
    }


def buyback_status(database_path: str | None = None) -> dict:
    latest_anchor = _latest_reported_cash_anchor(database_path)
    historical_gaps = buyback_coverage_gaps(database_path)
    current_gaps = (
        buyback_coverage_gaps(database_path, since_date=latest_anchor)
        if latest_anchor is not None
        else historical_gaps
    )
    with get_connection(database_path) as connection:
        aggregate = connection.execute("""
            SELECT COUNT(*) AS n, MIN(trade_date) AS min_date, MAX(trade_date) AS max_date,
                   SUM(shares) AS shares, SUM(CAST(amount_nok AS REAL)) AS amount_nok
            FROM buybacks
            """).fetchone()
        latest = connection.execute("""
            SELECT trade_date, shares, avg_price_nok, amount_nok,
                   cumulative_program_shares, cumulative_program_avg_price_nok,
                   cumulative_program_amount_nok, treasury_shares_after
            FROM buybacks ORDER BY trade_date DESC, id DESC LIMIT 1
            """).fetchone()
        return {
            "status": (
                "ok"
                if aggregate["n"] and not current_gaps
                else ("incomplete" if aggregate["n"] else "empty")
            ),
            "latest_reported_cash_anchor": latest_anchor,
            "historical_coverage_complete": not historical_gaps,
            "historical_coverage_gaps": historical_gaps,
            "current_coverage_complete": not current_gaps,
            "current_coverage_gaps": current_gaps,
            "count": aggregate["n"],
            "from": aggregate["min_date"],
            "to": aggregate["max_date"],
            "shares_in_weekly_rows": aggregate["shares"],
            "amount_nok_in_weekly_rows": aggregate["amount_nok"],
            "latest": dict(latest) if latest is not None else None,
        }
