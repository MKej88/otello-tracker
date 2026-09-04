from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bemobi_news_translation import translate_bemobi_news

CATEGORY_LABELS = {
    "RESULTS": "Resultatrapport",
    "DIVIDEND": "Utbytte",
    "JCP": "Renter",
    "BUYBACK": "Tilbakekjøp",
    "M_AND_A": "Oppkjøp og transaksjoner",
    "CAPITAL": "Kapital",
    "GUIDANCE": "Utsikter",
    "CORPORATE": "Selskapsmelding",
    "OTHER": "Annet",
}
OSLO_TZ = ZoneInfo("Europe/Oslo")
MEDIA_JOB_NAME = "bemobi_media_refresh"
DEFAULT_MEDIA_WINDOW_DAYS = 30


def _current_oslo_date(now: datetime | None = None) -> date:
    """Return the calendar date users in Norway currently see."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(OSLO_TZ).date()


def _importance(category: str, nav_impact: str) -> str:
    if category in {"RESULTS", "DIVIDEND", "JCP", "M_AND_A", "CAPITAL"}:
        return "HIGH"
    if category == "BUYBACK" or nav_impact in {"DIRECT", "POTENTIAL"}:
        return "MEDIUM"
    return "LOW"


def _safe_url(value: Any) -> str | None:
    url = str(value or "").strip()
    return url if url.startswith(("https://", "http://")) else None


def _company_name(symbol: Any) -> str | None:
    """Return a display name only for companies covered by this dashboard."""
    return {"OTEC": "Otello", "BMOB3": "Bemobi"}.get(str(symbol or ""))


def _decode_payload(value: Any) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _error_count(metadata: dict[str, Any], error_message: Any) -> int:
    feed_errors = metadata.get("feed_errors")
    translation_errors = metadata.get("translation_errors")
    count = len(feed_errors) if isinstance(feed_errors, list) else 0
    count += len(translation_errors) if isinstance(translation_errors, list) else 0
    if count == 0 and str(error_message or "").strip():
        count = 1
    return count


async def _media_refresh_status(repository) -> dict[str, Any]:
    row = await repository.first(
        """
        SELECT started_at, finished_at, status, records_written,
               error_message, metadata_json
        FROM job_runs
        WHERE job_name=?
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (MEDIA_JOB_NAME,),
    )
    if row is None:
        return {
            "available": False,
            "status": None,
            "window_days": DEFAULT_MEDIA_WINDOW_DAYS,
        }

    metadata = _decode_payload(row.get("metadata_json"))
    return {
        "available": True,
        "status": row.get("status"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "feeds_checked": int(metadata.get("feeds_checked") or 0),
        "candidates": int(metadata.get("candidates") or 0),
        "written": int(row.get("records_written") or metadata.get("written") or 0),
        "skipped_existing": int(metadata.get("skipped_existing") or 0),
        "error_count": _error_count(metadata, row.get("error_message")),
        "initial_backfill": bool(metadata.get("initial_backfill")),
        "article_limit": int(metadata.get("article_limit") or 0),
        "window_days": int(metadata.get("window_days") or DEFAULT_MEDIA_WINDOW_DAYS),
        "error_message": str(row.get("error_message") or "")[:300] or None,
    }


def _news_item(row: dict[str, Any]) -> dict[str, Any]:
    category = str(row.get("category") or "OTHER")
    nav_impact = str(row.get("nav_impact") or "NONE")
    metadata = _decode_payload(row.get("metadata_json"))
    content_type = str(metadata.get("content_type") or "OFFICIAL").upper()
    is_media = content_type == "MEDIA"
    headline = row.get("headline")
    summary = row.get("summary")
    if row.get("symbol") == "BMOB3" and not is_media:
        headline, summary = translate_bemobi_news(
            headline=headline,
            summary=summary,
            metadata=metadata,
        )
    source = (
        metadata.get("publisher")
        if is_media and metadata.get("publisher")
        else row.get("source_name") or row.get("source_code")
    )
    url = (
        metadata.get("original_url")
        if is_media and metadata.get("original_url")
        else row.get("url")
    )
    category_label = (
        "Medieomtale"
        if is_media and category == "OTHER"
        else CATEGORY_LABELS.get(category, "Annet")
    )
    return {
        "id": int(row["id"]),
        "company": "Bemobi" if row.get("symbol") == "BMOB3" else "Otello",
        "headline": headline,
        "published_at": row.get("published_at"),
        "category": category,
        "category_label": category_label,
        "importance": _importance(category, nav_impact),
        "summary": summary,
        "source": source,
        "url": _safe_url(url),
        "content_type": "MEDIA" if is_media else "OFFICIAL",
        "original_language": metadata.get("original_language") if is_media else None,
    }


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
    today = date.fromisoformat(as_of_date) if as_of_date else _current_oslo_date()
    safe_limit = max(1, min(news_limit, 100))
    media_status = await _media_refresh_status(repository)
    news = []
    batch_size = safe_limit * 3
    offset = 0
    while len(news) < safe_limit:
        news_rows = await repository.all(
            """
            SELECT cn.id, cn.headline,
                   COALESCE(cn.published_at, sd.published_at) AS published_at,
                   cn.category, cn.nav_impact,
                   cn.summary, i.symbol, sd.url, s.code AS source_code,
                   s.name AS source_name, sd.metadata_json
            FROM company_news cn
            LEFT JOIN instruments i ON i.id=cn.issuer_instrument_id
            JOIN source_documents sd ON sd.id=cn.source_document_id
            JOIN sources s ON s.id=sd.source_id
            WHERE i.symbol IN ('OTEC', 'BMOB3')
            ORDER BY COALESCE(cn.published_at, sd.published_at) DESC, cn.id DESC
            LIMIT ? OFFSET ?
            """,
            (batch_size, offset),
        )
        for row in news_rows:
            metadata = _decode_payload(row.get("metadata_json"))
            if metadata.get("is_latest_version") is False:
                continue
            news.append(_news_item(row))
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
        WHERE i.symbol IN ('OTEC', 'BMOB3')
          AND (ca.ex_date >= ? OR ca.payment_date >= ?)
          AND ca.action_type IN ('DIVIDEND', 'JCP', 'DISTRIBUTION')
        ORDER BY COALESCE(ca.ex_date, ca.payment_date), ca.id
        """,
        (today.isoformat(), today.isoformat()),
    )
    for row in actions:
        company = _company_name(row.get("symbol"))
        if company is None:
            continue
        label = "renter" if row.get("action_type") == "JCP" else "utbytte/distribusjon"
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
        "media_status": media_status,
    }
