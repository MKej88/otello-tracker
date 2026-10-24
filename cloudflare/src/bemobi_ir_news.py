"""Official Bemobi document feed, independent of the delayed CVM bulk archive."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from urllib.parse import urlsplit

from bounded_response import read_response_text

COMPANY_ID = "deed72f2-beae-4c6f-b423-db57178bae31"
SOURCE_URL = "https://ri.bemobi.com.br/en/financial-information/documents-filed-at-cvm/"
FEED_URL = f"https://api.mziq.com/mzfilemanager/company/{COMPANY_ID}/filter/categories/year/meta"
STATE_KEY = "bemobi_official_news_v1"
CATEGORIES = ("comunicados", "aviso-acionistas", "fatos-relevantes-e-comunicados")
# Discover official results without guessing MZiQ internal category slugs.
REPORT_TITLES = (
    ("EARNINGS_PRESENTATION", re.compile(r"\b(?:earnings presentation|apresentacao de resultados)\b")),
    ("EARNINGS_RELEASE", re.compile(r"\b(?:earnings release|release de resultados|press release de resultados|relatorio de resultados)\b")),
    ("FINANCIAL_STATEMENTS", re.compile(
        r"\b(?:itr\s*[1-4][qt]\s*\d{2}|dfp\b|quarterly information|"
        r"standardized financial statements|consolidated financial statements|"
        r"demonstracoes financeiras|dfs consolidadas)\b"
    )),
)


def _report_kind(row: dict) -> str | None:
    title = " ".join(str(row.get(key) or "") for key in ("file_title", "file_name_original"))
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    for kind, pattern in REPORT_TITLES:
        if pattern.search(normalized):
            return kind
    return None

# Source-verified first-deploy observation, 17.10.2026. Never used over a live
# snapshot (including an empty one), or before the observation date.
BOOTSTRAP_DATE = "2026-10-17"
BOOTSTRAP_ROWS = [{
    "id": "60ff8d82-c729-4c37-8b3a-2be854f0d79f",
    "date": "2026-10-14", "title": "Notice to the Market - Statement of Disposal of a Significant Equity Interest",
    "original_title": "Comunicado ao Mercado - Declaração de Alienação de Participação Acionária Relevante",
    "url": f"https://filemanager-cdn.mziq.com/published/{COMPANY_ID}/07bc1843-1482-4adb-835a-8e435eb25c44",
    "category": "comunicados",
}]


def filing_key(title: str, published: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"^(?:comunicado ao mercado|aviso aos acionistas|fato relevante)\s*[-–—:]\s*", "", text)
    if "participacao acionaria" in text or "significant equity interest" in text:
        # This particular filing type has different titles at CVM and IR.
        text = "significant-equity-interest"
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return f"bemobi-filing:{published[:10]}:{text}"


def parse_ir_filings(payload, *, target_date: str, include_reports: bool = False) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Bemobi IR meldingsfeed returnerte feil")
    rows = (payload.get("data") or {}).get("document_metas")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Bemobi IR meldingsfeed har ukjent struktur")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("company_id") != COMPANY_ID:
            raise ValueError("Ugyldig selskap i Bemobi IR meldingsfeed")
        if row.get("is_published") is not True:
            continue
        is_notice = row.get("internal_name") in CATEGORIES
        document_kind = "NOTICE" if is_notice else (_report_kind(row) if include_reports else None)
        if document_kind is None:
            continue
        published = date.fromisoformat(str(row.get("file_published_date") or row.get("file_date") or "")[:10]).isoformat()
        if published > target_date:
            continue
        identifier = str(row.get("id") or "")
        title = str(row.get("file_title") or "").strip()
        original = str(row.get("file_name_original") or title).strip()
        url = str(row.get("file_url") or "")
        parsed = urlsplit(url)
        if (not identifier or not title or parsed.scheme != "https"
            or parsed.hostname not in {"api.mziq.com", "filemanager-cdn.mziq.com"}
            or COMPANY_ID not in parsed.path):
            raise ValueError("Bemobi IR dokument mangler gyldig ID, tittel eller offisiell dokumentlenke")
        result[identifier] = dict(id=identifier, date=published, title=title,
                                  original_title=original, url=url, category=row["internal_name"],
                                  document_kind=document_kind)
    return sorted(result.values(), key=lambda item: (item["date"], item["id"]), reverse=True)


async def refresh_ir_news(repository, *, target_date: str, fetcher=None) -> dict:
    """Refresh mandatory notices plus optional results from Bemobi's MZiQ feed.

    Never erase valid notices because discovery of additional categories fails.
    """
    if fetcher is None:
        from workers import fetch
        fetcher = fetch

    async def read_feed(year: int, categories: list[str], *, include_reports: bool):
        response = await fetcher(
            FEED_URL, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            body=json.dumps(dict(year=year, categories=categories, language="en_US", published=True)),
        )
        if not bool(getattr(response, "ok", False)):
            raise RuntimeError(
                f"Bemobi IR dokumentfeed: HTTP {getattr(response, 'status', 'unknown')}"
            )
        raw = await read_response_text(
            response, max_bytes=3 * 1024 * 1024, label="Bemobi IR dokumentfeed"
        )
        return parse_ir_filings(
            json.loads(raw), target_date=target_date, include_reports=include_reports
        )

    try:
        rows = {}
        year = date.fromisoformat(target_date).year
        years = (year, year - 1) if target_date[5:7] == "01" else (year,)
        report_feed_errors = []
        for selected in years:
            # Baseline notices are mandatory and independently validated.
            for item in await read_feed(selected, list(CATEGORIES), include_reports=False):
                rows[item["id"]] = item
            try:
                # Empty categories requests all official categories, when supported.
                for item in await read_feed(selected, [], include_reports=True):
                    if item["document_kind"] != "NOTICE":
                        rows[item["id"]] = item
            except Exception as exc:
                report_feed_errors.append(f"{selected}: {type(exc).__name__}: {str(exc)[:180]}")

        if report_feed_errors or not any(
            item["document_kind"] != "NOTICE" for item in rows.values()
        ):
            # A failed/empty optional feed does not prove reports were withdrawn.
            previous = await repository.first(
                "SELECT value FROM runtime_state WHERE key=? LIMIT 1", (STATE_KEY,)
            )
            try:
                stored = json.loads(str((previous or {}).get("value") or "{}"))
                for item in stored.get("rows", []):
                    if (isinstance(item, dict)
                        and item.get("document_kind") in {
                            "EARNINGS_RELEASE", "FINANCIAL_STATEMENTS",
                            "EARNINGS_PRESENTATION",
                        }
                        and item.get("id") not in rows):
                        rows[item["id"]] = item
            except (ValueError, TypeError, AttributeError):
                pass

        final_rows = sorted(
            rows.values(), key=lambda item: (item["date"], item["id"]), reverse=True
        )
        snapshot = dict(checked_date=target_date, rows=final_rows, source_url=SOURCE_URL)
        await repository.run(
            "INSERT INTO runtime_state(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (STATE_KEY, json.dumps(snapshot, ensure_ascii=False)),
        )
        return dict(
            status="ok", documents=len(final_rows), checked_date=target_date,
            report_feed_status="partial" if report_feed_errors else "ok",
            report_feed_errors=report_feed_errors[:2],
        )
    except Exception as exc:
        return dict(
            status="not_available", error=f"{type(exc).__name__}: {str(exc)[:450]}",
            last_good_preserved=True,
        )

async def official_ir_news(repository, *, target_date: str) -> tuple[list[dict], str | None]:
    row = await repository.first("SELECT value FROM runtime_state WHERE key=? LIMIT 1", (STATE_KEY,))
    if row:
        try:
            snapshot = json.loads(row["value"])
            records = snapshot["rows"]
            checked = date.fromisoformat(snapshot["checked_date"]).isoformat()
            if checked > target_date:
                raise ValueError("future observation")
            if not isinstance(records, list) or any(not isinstance(item, dict) or not all(key in item for key in ("id", "date", "title", "original_title", "url")) for item in records):
                raise ValueError("invalid rows")
        except (KeyError, ValueError, TypeError):
            return [], "Bemobi IR meldinger: lagrede data kunne ikke leses"
    elif target_date >= BOOTSTRAP_DATE:
        records, checked = BOOTSTRAP_ROWS, BOOTSTRAP_DATE
    else:
        return [], None
    age = (date.fromisoformat(target_date) - date.fromisoformat(checked)).days
    warning = "Bemobi IR meldinger: siste vellykkede kildekontroll er forsinket" if age > 1 else None
    items = []
    for record in records:
        if record["date"] > target_date:
            continue
        title = record["title"]
        if "significant equity interest" in title.lower():
            title = "Bemobi – melding om salg av vesentlig aksjepost"
        is_report = record.get("document_kind") in {
            "EARNINGS_RELEASE", "FINANCIAL_STATEMENTS", "EARNINGS_PRESENTATION",
        }
        items.append(dict(
            id="bemobi-ir-" + record["id"], company="Bemobi", headline=title,
            published_at=record["date"],
            category="RESULTS" if is_report else "CORPORATE",
            category_label="Resultatrapport" if is_report else "Selskapsmelding",
            importance="MEDIUM", classification="REVIEW",
            reason="Offisielt Bemobi-dokument; innholdet må vurderes.",
            case_effect=None, nav_impact="NONE", summary="Offentlig dokument fra Bemobis IR-side. Ingen automatisk endring i NAV eller kontantstrøm.",
            source="Bemobi IR", url=record["url"], original_url=record["url"], translation_status="NOT_REQUIRED",
            translated_pdf_url=None, content_type="OFFICIAL",
            deduplication_key=filing_key(record["original_title"], record["date"]),
        ))
    return items, warning
