from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from bemobi_news_translation import translate_bemobi_news

CATEGORY_LABELS = {
    "RESULTS": "Resultatrapport",
    "DIVIDEND": "Utbytte",
    "JCP": "Kapitaldistribusjon",
    "BUYBACK": "Tilbakekjøp",
    "M_AND_A": "Oppkjøp og transaksjoner",
    "CAPITAL": "Kapital",
    "GUIDANCE": "Utsikter",
    "CORPORATE": "Selskapsmelding",
    "OTHER": "Annet",
}


def _importance(category: str, nav_impact: str) -> str:
    if category in {"RESULTS", "DIVIDEND", "JCP", "M_AND_A", "CAPITAL"}:
        return "HIGH"
    if category == "BUYBACK" or nav_impact in {"DIRECT", "POTENTIAL"}:
        return "MEDIUM"
    return "LOW"


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
    headline = row.get("headline")
    summary = row.get("summary")
    if row.get("symbol") == "BMOB3":
        headline, summary = translate_bemobi_news(
            headline=headline,
            summary=summary,
            metadata=_decode_payload(row.get("metadata_json")),
        )
    return {
        "id": int(row["id"]),
        "company": "Bemobi" if row.get("symbol") == "BMOB3" else "Otello",
        "headline": headline,
        "published_at": row.get("published_at"),
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, "Annet"),
        "importance": _importance(category, nav_impact),
        "summary": summary,
        "source": row.get("source_name") or row.get("source_code"),
        "url": _safe_url(row.get("url")),
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
    today = date.fromisoformat(as_of_date) if as_of_date else date.today()
    safe_limit = max(1, min(news_limit, 100))
    news_rows = await repository.all(
        """
        SELECT cn.id, cn.headline, cn.published_at, cn.category, cn.nav_impact,
               cn.summary, i.symbol, sd.url, s.code AS source_code,
               s.name AS source_name, sd.metadata_json
        FROM company_news cn
        LEFT JOIN instruments i ON i.id=cn.issuer_instrument_id
        JOIN source_documents sd ON sd.id=cn.source_document_id
        JOIN sources s ON s.id=sd.source_id
        WHERE i.symbol IN ('OTEC', 'BMOB3')
        ORDER BY COALESCE(cn.published_at, sd.published_at) DESC, cn.id DESC
        LIMIT ?
        """,
        (safe_limit * 3,),
    )
    news = []
    for row in news_rows:
        metadata = _decode_payload(row.get("metadata_json"))
        if metadata.get("is_latest_version") is False:
            continue
        news.append(_news_item(row))
        if len(news) >= safe_limit:
            break

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
