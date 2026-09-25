"""Bemobi's official MZ calendar, separate from quarterly financial estimates."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from bounded_response import read_response_text

SOURCE_URL = "https://ri.bemobi.com.br/en/our-actions/agenda/"
# Published as ajaxurlFuture / fmId in the official agenda page.
FEED_URL = "https://api.mziq.com/mzevents/events/future/deed72f2-beae-4c6f-b423-db57178bae31/en"
STATE_KEY = "bemobi_official_agenda_v1"
OSLO = ZoneInfo("Europe/Oslo")

# Verified first-deploy snapshot from FEED_URL on this date. The nightly job
# replaces the entire snapshot (including removals/reschedules), even if empty.
# Never used ahead of its observation date or over a successfully fetched cache.
BOOTSTRAP_DATE = "2026-09-25"
BOOTSTRAP_ROWS = [
    {"event_id": "749dc52c-5d8d-43ed-94dc-4483973eb1cd", "event_name": "Earning Release - 3Q26", "event_date": "2026-11-12T12:00:00.000Z", "google_cal_url": "https://www.google.com/calendar/render?dates=20261112%2F20261113"},
    {"event_id": "a9001d4a-618e-41a8-ad6c-30b1361761dc", "event_name": "Earnings Conference Call 3Q26", "event_date": "2026-11-13T12:00:00.000Z", "google_cal_url": "https://www.google.com/calendar/render?dates=20261113%2F20261114"},
]


def _start_at(row: dict[str, Any]) -> datetime | None:
    # event_date contains a noon placeholder even for date-only events. Use
    # the official calendar export's timed dates, never that placeholder.
    query = parse_qs(urlsplit(str(row.get("google_cal_url") or "")).query)
    start = query.get("dates", [""])[0].split("/")[0]
    if re.fullmatch(r"\d{8}", start) or not start:
        return None
    if not re.fullmatch(r"\d{8}T\d{6}Z?", start):
        raise ValueError("Ugyldig tidspunkt i Bemobi-kalenderen")
    parsed = datetime.strptime(start.rstrip("Z"), "%Y%m%dT%H%M%S")
    if start.endswith("Z"):
        return parsed.replace(tzinfo=UTC)
    timezone = query.get("ctz", [None])[0]
    if not timezone:
        return None  # An unqualified local time cannot be converted safely.
    return parsed.replace(tzinfo=ZoneInfo(timezone))


def parse_agenda(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, list) or len(payload) > 200:
        raise ValueError("Bemobi-kalenderen har ukjent struktur")
    events = []
    seen = set()
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("Ugyldig kalenderhendelse")
        identifier = str(row.get("event_id") or "")
        title = str(row.get("event_name") or "").strip()
        if not identifier or not title or identifier in seen:
            raise ValueError("Bemobi-kalenderen mangler entydig ID/tittel")
        seen.add(identifier)
        event_date = date.fromisoformat(str(row.get("event_date") or "")[:10]).isoformat()
        instant = _start_at(row)
        starts_at = instant.astimezone(UTC).isoformat().replace("+00:00", "Z") if instant else None
        if instant:
            event_date = instant.astimezone(OSLO).date().isoformat()
        period_match = re.search(r"\b([1-4])Q(\d{2}|\d{4})\b", title, re.I)
        period = None
        if period_match:
            year = int(period_match[2])
            period = f"{year + 2000 if year < 100 else year}Q{period_match[1]}"
        lower = title.lower()
        kind = "CONFERENCE_CALL" if "conference call" in lower else "RESULTS" if "release" in lower and "earning" in lower else "CORPORATE"
        if period and kind in {"RESULTS", "CONFERENCE_CALL"}:
            title = f"Bemobi – {'resultatrapport' if kind == 'RESULTS' else 'resultatpresentasjon'} Q{period[-1]} {period[:4]}"
        events.append({
            "id": f"bemobi-agenda-{identifier}", "date": event_date,
            "starts_at_utc": starts_at, "time_status": "CONFIRMED" if instant else "NOT_PUBLISHED",
            "company": "Bemobi", "title": title, "period": period,
            "category": kind, "importance": "HIGH" if kind in {"RESULTS", "CONFERENCE_CALL"} else "LOW",
            "date_label": "Rapportdato" if kind == "RESULTS" else "Presentasjon" if kind == "CONFERENCE_CALL" else "Hendelse",
            "confirmed": True, "source": "Bemobi IR – offisiell kalender", "url": SOURCE_URL,
        })
    return sorted(events, key=lambda x: (x["date"], x["starts_at_utc"] or "", x["id"]))


async def refresh_agenda(repository, *, target_date: str, fetcher=None) -> dict[str, Any]:
    """Independent daily refresh; preserve the last good snapshot on any failure."""
    try:
        if fetcher is None:
            from workers import fetch
            fetcher = fetch
        async def download():
            response = await fetcher(FEED_URL, headers={"Accept": "application/json"})
            if not response.ok:
                raise ValueError(f"Bemobi agenda HTTP {response.status}")
            return await read_response_text(response, max_bytes=512 * 1024, label="Bemobi agenda")
        events = parse_agenda(json.loads(await asyncio.wait_for(download(), timeout=15)))
        observed_at = datetime.now(UTC).isoformat()
        await repository.run(
            "INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (STATE_KEY, json.dumps({"events": events, "observed_date": target_date, "source_url": SOURCE_URL, "feed_url": FEED_URL}), observed_at),
        )
        return {"status": "ok", "events": len(events), "rows_written": 1, "source_url": SOURCE_URL}
    except Exception as exc:
        return {"status": "not_available", "error": f"{type(exc).__name__}: {exc}", "last_good_preserved": True, "rows_written": 0, "source_url": SOURCE_URL}


async def agenda_events(repository, *, as_of_date: str) -> list[dict[str, Any]]:
    events = parse_agenda(BOOTSTRAP_ROWS) if as_of_date >= BOOTSTRAP_DATE else []
    row = await repository.first("SELECT value FROM runtime_state WHERE key=?", (STATE_KEY,))
    cached = json.loads(str(row.get("value") or "{}")) if row else {}
    if isinstance(cached.get("events"), list) and str(cached.get("observed_date") or "9999") <= as_of_date:
        events = cached["events"]
    return [event for event in events if event["date"] >= as_of_date]


def merge_agenda_events(existing: list[dict[str, Any]], agenda: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # The official agenda supersedes the separate next-quarter estimate for the
    # same period, including when IR has rescheduled it to a different date.
    periods = {x.get("period") for x in agenda if x.get("category") == "RESULTS"}
    ids = {x["id"] for x in agenda}
    output = [x for x in existing if x["id"] not in ids and not (
        str(x["id"]).startswith("bemobi-report-") and str(x["id"])[len("bemobi-report-"):] in periods
    )]
    return sorted(output + agenda, key=lambda x: (x["date"], x.get("starts_at_utc") or "", x["id"]))
