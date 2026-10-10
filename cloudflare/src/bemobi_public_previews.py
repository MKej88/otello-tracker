"""Bounded public broker discovery; Q3 watch ends when the result is ingested."""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin, urlparse

from bemobi_web_refresh import (
    MAX_HTML_BYTES,
    _clean,
    _decode_html,
    _fetch_bytes,
    _html_parser,
    _period_from_text,
    _store_web_document,
    _upsert_fact,
    sync_xp_preview,
)

BTG_INDEX_URL = "https://content.btgpactual.com/research/home"
BTG_Q3_URL = (
    "https://content.btgpactual.com/research/home/relatorio/"
    "6ac79ea65a2606707e77d83d/Telecom-Tech-Previa-3T26-II"
)
WATCH_PERIOD = "3Q26"


def bemobi_preview_text(html: str) -> str | None:
    """Isolate Bemobi before reading numbers from a multi-company sector note."""
    html = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL
    )
    text = _clean(unescape(re.sub(r"<[^>]+>", " ", html)))
    section = re.search(
        r"\b(?:Bemobi(?:\s*\(BMOB3\))?|BMOB3)\s*[:–—|]\s*(.*?)(?=\bTabela\s+\d|\b[A-Z][\w ]{1,30}:|$)",
        text,
        re.DOTALL,
    )
    if section:
        return section.group(1)
    # A company-specific page can use Bemobi without a colon. Do not fall back
    # to the entire text of a sector report: it may contain peers' EBITDA.
    if re.search(r"\b(bemobi|bmob3)\b", text, re.IGNORECASE) and not re.search(
        r"\b(intelbras|totvs|lwsa|locaweb)\b", text, re.IGNORECASE
    ):
        return text
    return None


def parse_btg_preview_html(html: str) -> dict | None:
    parser = _html_parser(html)
    text = _clean(unescape(re.sub(r"<[^>]+>", " ", html)))
    period = _period_from_text(text)
    section = bemobi_preview_text(html)
    if (
        not period
        or not section
        or not re.search(r"pr[eé]via|preview", text, re.IGNORECASE)
    ):
        return None
    published = parser.meta.get("article:published_time") or parser.meta.get("date")
    if published and re.match(r"20\d{2}-\d{2}-\d{2}", published):
        published_date = published[:10]
    else:
        match = re.search(r"\b(\d{2})/(\d{2})/(20\d{2})\b", text)
        if not match:
            return None
        published_date = f"{match[3]}-{match[2]}-{match[1]}"
    estimates = []
    patterns = (
        (
            "revenue_yoy_pct",
            "Omsetningsvekst år/år",
            r"crescimento de ([\d,.]+)% a/a na receita",
            "value_pct",
        ),
        (
            "ebitda_yoy_pct",
            "EBITDA-vekst år/år",
            r"EBITDA a crescer ([\d,.]+)% a/a",
            "value_pct",
        ),
        (
            "ebitda_margin_pct",
            "EBITDA-margin",
            r"margem EBITDA deve alcan[çc]ar ([\d,.]+)%",
            "value_pct",
        ),
        (
            "cash_profit_mbrl",
            "Cash profit (BTGs definisjon)",
            r"(?:cash\s+)?lucro caixa de R\$\s*([\d,.]+) milh[õo]es",
            "value_mbrl",
        ),
    )
    for metric, label, pattern, field in patterns:
        match = re.search(pattern, section, re.IGNORECASE)
        if match:
            value = float(match[1].replace(",", "."))
            limit = 100 if metric == "ebitda_margin_pct" else 2_000
            if not 0 <= value <= limit:
                return None
            estimates.append({"metric": metric, "label": label, field: value})
    if not estimates:
        return None
    return {"period": period, "published_date": published_date, "estimates": estimates}


async def store_public_preview(
    repository,
    *,
    latest: dict,
    preview: dict,
    broker: str,
    url: str,
    document_id: int | None,
    target_date: str,
) -> bool:
    """Keep other brokers and reject older publications, regardless of check date."""
    existing = json.loads(str(latest.get("payload_json") or "{}"))
    estimates = existing.get("estimates") or []
    old_dates = [
        str(item.get("published_date") or "")
        for item in estimates
        if item.get("broker") == broker
    ]
    published = preview.get("published_date")
    if (
        not published
        or published > target_date
        or (old_dates and published < max(old_dates))
    ):
        return False
    updated = {
        **existing,
        "period": preview["period"],
        "status": "PUBLIC_ESTIMATES_AVAILABLE",
        "estimates": [item for item in estimates if item.get("broker") != broker]
        + [
            {**item, "broker": broker, "source_url": url, "published_date": published}
            for item in preview["estimates"]
        ],
        "note": "Offentlige meglerhusestimater vises hver for seg; ikke markedskonsensus. Cash profit følger BTGs definisjon.",
    }
    await _upsert_fact(
        repository,
        fact_type="NEXT_QUARTER",
        fact_key=preview["period"],
        as_of_date=target_date,
        published_date=published,
        payload=updated,
        source_name=broker,
        source_url=url,
        source_document_id=document_id,
        quality="PUBLIC_BROKER_PREVIEW_AUTO",
        notes="Offentlig forhåndsestimat med kilde, publiseringsdato og separate måltallsdefinisjoner.",
    )
    return True


async def sync_btg_preview(
    repository, *, target_date: str, archive_bucket=None, fetcher=None
) -> dict:
    latest = await repository.first(
        "SELECT fact_key, payload_json FROM bemobi_investor_facts WHERE fact_type='NEXT_QUARTER' "
        "ORDER BY COALESCE(as_of_date, published_date, '') DESC, id DESC LIMIT 1"
    )
    if latest is None:
        return {
            "status": "skipped",
            "reason": "next_quarter_not_initialized",
            "rows_written": 0,
        }
    candidates = [BTG_Q3_URL]
    errors = []
    try:
        raw = await _fetch_bytes(
            BTG_INDEX_URL,
            label="BTG research index",
            max_bytes=MAX_HTML_BYTES,
            fetcher=fetcher,
        )
        discovered = 0
        for href, label in _html_parser(_decode_html(raw)).links:
            url = urljoin(BTG_INDEX_URL, href)
            parsed = urlparse(url)
            # Sector previews qualify even when their title has no Bemobi/BMOB3.
            if (
                parsed.scheme == "https"
                and parsed.hostname == "content.btgpactual.com"
                and "/relatorio/" in parsed.path
                and re.search(r"pr[eé]via|preview", f"{url} {label}", re.IGNORECASE)
            ):
                candidates.append(url)
                discovered += 1
        if not discovered:
            errors.append(
                "BTG-indeksen eksponerer ingen preview-lenker i HTML; kjent rapport kontrolleres, men nye rapporter krever et supplerende nettsøk."
            )
    except Exception as exc:  # noqa: BLE001 - record optional-source failures and preserve last good data
        errors.append(str(exc)[:300])
    found = []
    for url in list(dict.fromkeys(candidates))[:8]:
        try:
            raw = await _fetch_bytes(
                url,
                label="BTG sector preview",
                max_bytes=MAX_HTML_BYTES,
                fetcher=fetcher,
            )
            preview = parse_btg_preview_html(_decode_html(raw))
            if (
                preview
                and preview["period"] == latest["fact_key"]
                and preview["published_date"] <= target_date
            ):
                found.append((preview, url, raw))
        except Exception as exc:  # noqa: BLE001 - record optional-source failures and preserve last good data
            errors.append(str(exc)[:300])
    if not found:
        return {
            "status": "not_available",
            "reason": "no_public_preview_for_next_quarter",
            "rows_written": 0,
            "errors": errors[:3],
        }
    preview, url, raw = max(found, key=lambda item: item[0]["published_date"])
    document_id = await _store_web_document(
        repository,
        archive_bucket,
        source_code="BTG_PACTUAL",
        url=url,
        kind="bemobi-preview",
        title=f"BTG Pactual Bemobi preview {preview['period']}",
        target_date=preview["published_date"],
        payload=raw,
    )
    written = await store_public_preview(
        repository,
        latest=latest,
        preview=preview,
        broker="BTG Pactual",
        url=url,
        document_id=document_id,
        target_date=target_date,
    )
    return {
        "status": "ok",
        "period": preview["period"],
        "rows_written": int(written),
        "source_url": url,
        "discovery_errors": errors[:3],
        "discovery_status": "degraded" if errors else "ok",
    }


async def sync_q3_previews(
    repository, *, target_date: str, archive_bucket=None, fetcher=None
) -> dict:
    pending = await repository.first(
        "SELECT fact_key FROM bemobi_investor_facts WHERE fact_type='NEXT_QUARTER' "
        "ORDER BY COALESCE(as_of_date, published_date, '') DESC, id DESC LIMIT 1"
    )
    result = await repository.first(
        "SELECT id FROM bemobi_investor_facts WHERE fact_type='RESULT' AND fact_key=? LIMIT 1",
        (WATCH_PERIOD,),
    )
    if result or not pending or pending["fact_key"] != WATCH_PERIOD:
        return {
            "status": "skipped",
            "reason": "q3_watch_not_pending",
            "rows_written": 0,
        }
    # Sequential writes: both brokers share NEXT_QUARTER and must see each other.
    xp = await sync_xp_preview(
        repository,
        target_date=target_date,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )
    try:
        btg = await sync_btg_preview(
            repository,
            target_date=target_date,
            archive_bucket=archive_bucket,
            fetcher=fetcher,
        )
    except Exception as exc:  # noqa: BLE001 - record optional-source failures and preserve last good data
        btg = {"status": "not_available", "error": str(exc)[:700], "rows_written": 0}
    return {
        "status": "ok",
        "period": WATCH_PERIOD,
        "xp_preview": xp,
        "btg_preview": btg,
        "rows_written": int(xp.get("rows_written") or 0)
        + int(btg.get("rows_written") or 0),
    }
