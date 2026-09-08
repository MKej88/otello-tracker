from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from typing import Any

from app.bemobi_news_translation import translate_bemobi_news
from app.db.connection import get_connection

CATEGORY_LABELS = {
    "RESULTS": "Resultatrapport",
    "DIVIDEND": "Utbytte",
    "JCP": "JCP",
    "BUYBACK": "Tilbakekjøp",
    "M_AND_A": "Oppkjøp og transaksjoner",
    "CAPITAL": "Kapital",
    "GUIDANCE": "Utsikter",
    "CORPORATE": "Selskapsmelding",
    "OTHER": "Annet",
}


MATERIAL_CATEGORIES = {"DIVIDEND", "JCP", "BUYBACK", "M_AND_A", "CAPITAL", "GUIDANCE"}
REVIEW_STATUSES = {"NEW", "REVIEW_REQUIRED"}
REASON_LABELS = {
    "DIVIDEND": "Dokumentdata identifiserer et konkret utbytte.",
    "JCP": "Dokumentdata identifiserer en konkret JCP-hendelse.",
    "BUYBACK": "Dokumentdata identifiserer et konkret tilbakekjøp.",
    "M_AND_A": "Dokumentdata identifiserer en konkret selskapstransaksjon.",
    "CAPITAL": "Dokumentdata identifiserer en konkret kapitalhendelse.",
    "GUIDANCE": "Dokumentdata identifiserer en konkret endring i guiding.",
}


def _classification(
    category: str,
    nav_impact: str,
    processing_status: str,
    metadata: dict[str, Any],
) -> tuple[str, str, str | None]:
    """Classify only documented signals, never the filing type by itself."""
    reason = str(metadata.get("classification_reason") or "").strip()
    requires_review = metadata.get("requires_review") is True
    has_concrete_reason = (
        category in MATERIAL_CATEGORIES
        and bool(reason)
        and not requires_review
        and processing_status not in REVIEW_STATUSES
    )
    if has_concrete_reason:
        case_effect = (
            "Direkte effekt på verdi eller kontantstrøm er registrert."
            if nav_impact == "DIRECT"
            else "Den identifiserte hendelsen kan påvirke verdi, kontantstrøm eller risiko."
        )
        return "CONFIRMED_IMPORTANT", REASON_LABELS[category], case_effect

    governance_filing = str(metadata.get("cvm_category") or "").lower() in {
        "reunião da administração",
        "assembleia",
    }
    if (
        processing_status in REVIEW_STATUSES
        or category in MATERIAL_CATEGORIES
        or governance_filing
    ):
        return (
            "REVIEW",
            "Dokumentet er ikke ferdig analysert, eller mangler en konkret begrunnelse.",
            None,
        )
    return "INFORMATION", "Ingen materiell endring er identifisert.", None


def _importance(classification: str) -> str:
    """Keep the old API field, but derive it from the stricter classification."""
    return {
        "CONFIRMED_IMPORTANT": "HIGH",
        "POSSIBLY_IMPORTANT": "MEDIUM",
        "REVIEW": "LOW",
        "INFORMATION": "LOW",
    }[classification]


def _safe_url(value: Any) -> str | None:
    url = str(value or "").strip()
    return url if url.startswith(("https://", "http://")) else None


def _decode_payload(value: Any) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _news_item(row: dict[str, Any]) -> dict[str, Any]:
    category = str(row.get("category") or "OTHER")
    nav_impact = str(row.get("nav_impact") or "NONE")
    metadata = _decode_payload(row.get("metadata_json"))
    processing_status = str(row.get("processing_status") or "NEW")
    classification, reason, case_effect = _classification(
        category, nav_impact, processing_status, metadata
    )
    headline = row.get("headline")
    summary = row.get("summary")
    if row.get("symbol") == "BMOB3":
        headline, summary = translate_bemobi_news(
            headline=headline,
            summary=summary,
            metadata=metadata,
        )
    return {
        "id": int(row["id"]),
        "company": "Bemobi" if row.get("symbol") == "BMOB3" else "Otello",
        "headline": headline,
        "published_at": row.get("published_at"),
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, "Annet"),
        "importance": _importance(classification),
        "classification": classification,
        "reason": reason,
        "case_effect": case_effect,
        "nav_impact": nav_impact,
        "summary": summary,
        "source": row.get("source_name") or row.get("source_code"),
        "url": _safe_url(row.get("url")),
        "content_type": "OFFICIAL",
        "deduplication_key": _deduplication_key(row, metadata),
    }


def _deduplication_key(row: dict[str, Any], metadata: dict[str, Any]) -> str:
    """Group exact/logical duplicates while preserving distinct material events."""
    logical_key = str(metadata.get("logical_key") or "").strip()
    if logical_key and row.get("category") not in MATERIAL_CATEGORIES:
        return f"logical:{logical_key}"
    content_hash = str(row.get("content_sha256") or "").strip()
    if content_hash:
        return f"content:{content_hash}"
    url = _safe_url(row.get("url"))
    if url:
        return f"url:{url}"
    normalized_headline = re.sub(
        r"\s+", " ", str(row.get("headline") or "").lower()
    ).strip()
    published_date = str(row.get("published_at") or "")[:10]
    return f"fallback:{row.get('symbol')}:{published_date}:{normalized_headline}"


def _event(
    *,
    event_id: str,
    event_date: str,
    company: str,
    title: str,
    category: str,
    importance: str,
    date_label: str,
    source: Any,
    url: Any,
    confirmed: bool = True,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "date": event_date,
        "company": company,
        "title": title,
        "category": category,
        "importance": importance,
        "date_label": date_label,
        "confirmed": confirmed,
        "source": source,
        "url": _safe_url(url),
    }


async def news_and_events(
    repository,
    *,
    as_of_date: str | None = None,
    news_limit: int = 60,
) -> dict[str, Any]:
    today = date.fromisoformat(as_of_date) if as_of_date else date.today()
    safe_limit = max(1, min(news_limit, 100))
    news = []
    seen_documents: set[str] = set()
    batch_size = safe_limit * 3
    offset = 0
    while len(news) < safe_limit:
        news_rows = await repository.all(
            """
        SELECT cn.id, cn.headline,
               COALESCE(cn.published_at, sd.published_at) AS published_at,
               cn.category, cn.nav_impact, cn.processing_status,
               cn.summary, i.symbol, sd.url, s.code AS source_code,
               s.name AS source_name, sd.metadata_json, sd.content_sha256
        FROM company_news cn
        LEFT JOIN instruments i ON i.id=cn.issuer_instrument_id
        JOIN source_documents sd ON sd.id=cn.source_document_id
        JOIN sources s ON s.id=sd.source_id
        WHERE i.symbol IN ('OTEC', 'BMOB3')
          AND s.code IN ('NEWSWEB', 'CVM', 'BEMOBI_IR')
        ORDER BY COALESCE(cn.published_at, sd.published_at) DESC, cn.id DESC
        LIMIT ? OFFSET ?
        """,
            (batch_size, offset),
        )
        for row in news_rows:
            metadata = _decode_payload(row.get("metadata_json"))
            if metadata.get("is_latest_version") is False:
                continue
            item = _news_item(row)
            deduplication_key = str(item.pop("deduplication_key"))
            if deduplication_key in seen_documents:
                continue
            seen_documents.add(deduplication_key)
            news.append(item)
            if len(news) >= safe_limit:
                break
        if len(news_rows) < batch_size:
            break
        offset += batch_size

    events: list[dict[str, Any]] = []
    programs = await repository.all(
        """
        SELECT p.id, p.start_date, p.end_date, p.status, sd.url,
               s.name AS source_name
        FROM buyback_programs p
        LEFT JOIN source_documents sd ON sd.id=p.source_document_id
        LEFT JOIN sources s ON s.id=sd.source_id
        WHERE p.end_date >= ? AND p.status='ACTIVE'
        ORDER BY p.start_date, p.id
        """,
        (today.isoformat(),),
    )
    for row in programs:
        start_date = row.get("start_date")
        if start_date and str(start_date) >= today.isoformat():
            events.append(
                _event(
                    event_id=f"buyback-start-{row['id']}",
                    event_date=str(row["start_date"]),
                    company="Otello",
                    title="Tilbakekjøpsprogram starter",
                    category="BUYBACK",
                    importance="HIGH",
                    date_label="Startdato",
                    source=row.get("source_name"),
                    url=row.get("url"),
                )
            )
        events.append(
            _event(
                event_id=f"buyback-end-{row['id']}",
                event_date=str(row["end_date"]),
                company="Otello",
                title="Siste planlagte dag i tilbakekjøpsprogrammet",
                category="BUYBACK",
                importance="HIGH",
                date_label="Sluttdato",
                source=row.get("source_name"),
                url=row.get("url"),
            )
        )

    actions = await repository.all(
        """
        SELECT ca.id, ca.action_type, ca.ex_date, ca.payment_date, i.symbol,
               sd.url, s.name AS source_name
        FROM corporate_actions ca
        JOIN instruments i ON i.id=ca.issuer_instrument_id
        JOIN source_documents sd ON sd.id=ca.source_document_id
        JOIN sources s ON s.id=sd.source_id
        WHERE (ca.ex_date >= ? OR ca.payment_date >= ?)
          AND ca.action_type IN ('DIVIDEND', 'JCP', 'DISTRIBUTION')
        ORDER BY COALESCE(ca.ex_date, ca.payment_date), ca.id
        """,
        (today.isoformat(), today.isoformat()),
    )
    for row in actions:
        company = "Bemobi" if row.get("symbol") == "BMOB3" else "Otello"
        label = "JCP" if row.get("action_type") == "JCP" else "utbytte/distribusjon"
        for field, date_label in (
            ("ex_date", "Ex-dato"),
            ("payment_date", "Betalingsdato"),
        ):
            event_date = row.get(field)
            if event_date and str(event_date) >= today.isoformat():
                events.append(
                    _event(
                        event_id=f"action-{row['id']}-{field}",
                        event_date=str(event_date),
                        company=company,
                        title=f"{date_label} for {label}",
                        category="DISTRIBUTION",
                        importance="HIGH",
                        date_label=date_label,
                        source=row.get("source_name"),
                        url=row.get("url"),
                    )
                )

    next_quarter = await repository.first("""
        SELECT fact_key, payload_json, source_name, source_url
        FROM bemobi_investor_facts
        WHERE fact_type='NEXT_QUARTER'
        ORDER BY COALESCE(as_of_date, published_date, '') DESC, id DESC
        LIMIT 1
        """)
    if next_quarter:
        payload = _decode_payload(next_quarter.get("payload_json"))
        report_date = payload.get("report_date")
        if report_date and str(report_date) >= today.isoformat():
            events.append(
                _event(
                    event_id=f"bemobi-report-{next_quarter['fact_key']}",
                    event_date=str(report_date),
                    company="Bemobi",
                    title=f"Bemobi rapporterer {next_quarter['fact_key']}",
                    category="RESULTS",
                    importance="HIGH",
                    date_label="Rapportdato",
                    confirmed=payload.get("date_quality") == "CONFIRMED",
                    source=next_quarter.get("source_name"),
                    url=next_quarter.get("source_url"),
                )
            )

    active_program = next(
        (
            row
            for row in programs
            if row.get("start_date") and str(row["start_date"]) <= today.isoformat()
        ),
        None,
    )
    if active_program:
        days_until_monday = (7 - today.weekday()) % 7 or 7
        expected_date = today + timedelta(days=days_until_monday)
        if expected_date <= date.fromisoformat(str(active_program["end_date"])):
            events.append(
                _event(
                    event_id=f"expected-buyback-{expected_date.isoformat()}",
                    event_date=expected_date.isoformat(),
                    company="Otello",
                    title="Neste forventede tilbakekjøpsrapport",
                    category="BUYBACK",
                    importance="MEDIUM",
                    date_label="Forventet dato",
                    confirmed=False,
                    source=active_program.get("source_name"),
                    url=active_program.get("url"),
                )
            )

    events.sort(key=lambda item: (item["date"], item["id"]))
    return {
        "ready": True,
        "as_of_date": today.isoformat(),
        "news": news,
        "events": events[:40],
        "counts": {"news": len(news), "events": min(len(events), 40)},
    }


class SQLiteNewsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    async def all(
        self,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    async def first(
        self,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        row = self.connection.execute(query, params).fetchone()
        return None if row is None else dict(row)


async def news_events_dashboard(
    database_path: str | None = None,
    *,
    as_of_date: str | None = None,
    news_limit: int = 60,
) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        return await news_and_events(
            SQLiteNewsRepository(connection),
            as_of_date=as_of_date,
            news_limit=news_limit,
        )
