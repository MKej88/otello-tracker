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


def parse_ir_filings(payload, *, target_date: str) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Bemobi IR meldingsfeed returnerte feil")
    rows = (payload.get("data") or {}).get("document_metas")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Bemobi IR meldingsfeed har ukjent struktur")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("company_id") != COMPANY_ID:
            raise ValueError("Ugyldig selskap i Bemobi IR meldingsfeed")
        if row.get("is_published") is not True or row.get("internal_name") not in CATEGORIES:
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
                                  original_title=original, url=url, category=row["internal_name"])
    return sorted(result.values(), key=lambda item: (item["date"], item["id"]), reverse=True)


async def refresh_ir_news(repository, *, target_date: str, fetcher=None) -> dict:
    """A live success replaces the snapshot; failures preserve last-good data."""
    if fetcher is None:
        from workers import fetch
        fetcher = fetch
    try:
        rows = []
        year = date.fromisoformat(target_date).year
        # Include last year around New Year so a late December notice is retained.
        years = (year, year - 1) if target_date[5:7] == "01" else (year,)
        for selected in years:
            response = await fetcher(FEED_URL, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"},
                                     body=json.dumps(dict(year=selected, categories=list(CATEGORIES), language="en_US", published=True)))
            if not bool(getattr(response, "ok", False)):
                raise RuntimeError(f"Bemobi IR meldingsfeed: HTTP {getattr(response, 'status', 'unknown')}")
            raw = await read_response_text(response, max_bytes=3 * 1024 * 1024, label="Bemobi IR meldingsfeed")
            rows.extend(parse_ir_filings(json.loads(raw), target_date=target_date))
        snapshot = dict(checked_date=target_date, rows=rows, source_url=SOURCE_URL)
        await repository.run("INSERT INTO runtime_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                             (STATE_KEY, json.dumps(snapshot, ensure_ascii=False)))
        return dict(status="ok", documents=len(rows), checked_date=target_date)
    except Exception as exc:
        return dict(status="not_available", error=str(exc)[:500], last_good_preserved=True)


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
        items.append(dict(
            id="bemobi-ir-" + record["id"], company="Bemobi", headline=title,
            published_at=record["date"], category="CORPORATE", category_label="Selskapsmelding",
            importance="MEDIUM", classification="REVIEW", reason="Offisiell Bemobi-melding; dokumentinnholdet må vurderes.",
            case_effect=None, nav_impact="NONE", summary="Offentlig dokument fra Bemobis IR-side. Ingen automatisk endring i NAV eller kontantstrøm.",
            source="Bemobi IR", url=record["url"], original_url=record["url"], translation_status="NOT_REQUIRED",
            translated_pdf_url=None, content_type="OFFICIAL",
            deduplication_key=filing_key(record["original_title"], record["date"]),
        ))
    return items, warning
