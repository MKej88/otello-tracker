from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import brazil_dashboard as brazil_base
from brazil_focus_resilience import apply_cached_event_expectations

OSLO_TZ = ZoneInfo("Europe/Oslo")


def _current_oslo_date() -> date:
    return datetime.now(UTC).astimezone(OSLO_TZ).date()


def _decode_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    import json

    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _company_name(symbol: Any) -> str | None:
    if symbol == "BMOB3":
        return "Bemobi"
    if symbol == "OTEC":
        return "Otello"
    return None


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
        "url": str(url) if url else None,
    }


async def _company_events(repository: Any, *, today: date) -> list[dict[str, Any]]:
    today_iso = today.isoformat()
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
        (today_iso,),
    )
    for row in programs:
        start_date = row.get("start_date")
        if start_date and str(start_date) >= today_iso:
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
        (today_iso, today_iso),
    )
    for row in actions:
        company = _company_name(row.get("symbol"))
        if company is None:
            continue
        label = "JCP" if row.get("action_type") == "JCP" else "utbytte/distribusjon"
        for field, date_label in (
            ("ex_date", "Ex-dato"),
            ("payment_date", "Betalingsdato"),
        ):
            event_date = row.get(field)
            if event_date and str(event_date) >= today_iso:
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

    next_quarter = await repository.first(
        """
        SELECT fact_key, payload_json, source_name, source_url
        FROM bemobi_investor_facts
        WHERE fact_type='NEXT_QUARTER'
        ORDER BY COALESCE(as_of_date, published_date, '') DESC, id DESC
        LIMIT 1
        """
    )
    if next_quarter:
        payload = _decode_payload(next_quarter.get("payload_json"))
        report_date = payload.get("report_date")
        if report_date and str(report_date) >= today_iso:
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
            if row.get("start_date") and str(row["start_date"]) <= today_iso
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

    events.sort(key=lambda item: (str(item["date"]), str(item["id"])))
    return events[:40]


async def overview_events(
    repository: Any,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Return first-screen events without live calls to external macro providers.

    Company dates are read directly from D1. The Brazil calendar comes from the
    maintained official-date seed/rolling preview, while release time and true
    event consensus are restored only from the last-good D1 cache populated by
    the normal Brazil refresh path. Keep this request path read-only and free of
    external network dependencies so it remains suitable for first-screen bootstrap.
    """
    today = date.fromisoformat(as_of_date) if as_of_date else _current_oslo_date()
    today_iso = today.isoformat()

    company_events = await _company_events(repository, today=today)
    macro_calendar = brazil_base.calendar_events(as_of_date=today_iso, focus={})
    try:
        macro_calendar, restored = await apply_cached_event_expectations(
            repository,
            macro_calendar,
            as_of_date=today_iso,
        )
    except Exception:  # noqa: BLE001 - dates remain usable if cache read fails
        restored = 0

    return {
        "ready": True,
        "as_of_date": today_iso,
        "events": company_events,
        "calendar": macro_calendar[:40],
        "meta": {
            "source": "D1_LAST_GOOD",
            "cached_macro_expectations_restored": restored,
            "live_external_fetches": False,
        },
    }
