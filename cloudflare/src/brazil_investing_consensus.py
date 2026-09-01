from __future__ import annotations

import asyncio
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable

from bounded_response import read_response_bytes

MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# Offentlige hendelsessider hos Investing.com. Datoene i selve makrokalenderen
# kommer fortsatt fra IBGE/BCB; disse sidene brukes bare til publiseringstid,
# forrige verdi og hendelsesnær markedskonsensus (Forecast) når den finnes.
_EVENT_URLS = {
    "gdp": "https://www.investing.com/economic-calendar/brazil-gdp-858",
    "ipca": "https://www.investing.com/economic-calendar/brazil-consumer-price-index-%28cpi%29-mom-1165",
    "ipca-15": "https://www.investing.com/economic-calendar/brazil-mid-month-consumer-price-index-%28cpi%29-mom-1569",
    "services": "https://www.investing.com/economic-calendar/brazil-services-sector-growth-1880",
    "retail": "https://www.investing.com/economic-calendar/brazilian-retail-sales-861",
    "activity": "https://www.investing.com/economic-calendar/brazil---aktiviti-ekonomi-ibc-br-765",
    "labor": "https://www.investing.com/economic-calendar/brazilian-unemployment-rate-411",
    "copom": "https://www.investing.com/economic-calendar/interest-rate-decision-415",
}


def _event_source_key(event: dict[str, Any]) -> str | None:
    kind = str(event.get("kind") or "")
    if kind == "inflation":
        name = str(event.get("name") or "").lower()
        return "ipca-15" if "15" in name else "ipca"
    return kind if kind in _EVENT_URLS else None


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class _VisibleTextParser(HTMLParser):
    """Extract visible text without regex-based HTML sanitization."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _strip_html(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    return _compact(" ".join(parser.parts))


def _row_date(value: str) -> str | None:
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", _compact(value))
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _numeric_value(value: str) -> float | None:
    raw = _compact(value).replace("−", "-").replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_rows(page: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_match in re.finditer(r"<tr\b[^>]*>([\s\S]*?)</tr>", page, flags=re.I):
        cells = [
            _strip_html(cell.group(1))
            for cell in re.finditer(r"<td\b[^>]*>([\s\S]*?)</td>", row_match.group(1), flags=re.I)
        ]
        if len(cells) < 5:
            continue
        event_date = _row_date(cells[0])
        if event_date is None or not re.fullmatch(r"\d{1,2}:\d{2}", cells[1]):
            continue
        rows.append(
            {
                "date": event_date,
                "time_utc": cells[1],
                "actual": cells[2] or None,
                "forecast": cells[3] or None,
                "previous": cells[4] or None,
            }
        )
    return rows


async def _fetch_html(
    url: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> str:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    response = await fetcher(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (compatible; OtelloTracker/1.0; +https://otellotracker.com)",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"HTTP {getattr(response, 'status', 'unknown')} for {url}")
    payload = await read_response_bytes(
        response,
        max_bytes=MAX_RESPONSE_BYTES,
        label="Investing.com economic calendar HTML",
    )
    return payload.decode("utf-8", errors="replace")


def _merge_row(
    event: dict[str, Any],
    row: dict[str, Any],
    *,
    source_url: str,
    as_of_date: str,
) -> tuple[dict[str, Any], bool]:
    enriched = dict(event)
    expectation = dict(event.get("expectation") or {})
    hour_minute = str(row["time_utc"])
    expectation.update(
        {
            "release_at_utc": f"{row['date']}T{hour_minute}:00Z",
            "release_time_provider": "Investing.com",
            "release_time_source_url": source_url,
        }
    )

    forecast_text = str(row.get("forecast") or "").strip()
    forecast_value = _numeric_value(forecast_text)
    has_consensus = forecast_value is not None
    if has_consensus:
        unit = "%" if "%" in forecast_text else ""
        expectation.update(
            {
                "label": f"Investing.com-konsensus for {event.get('reference') or event.get('name') or 'hendelsen'}",
                "value": forecast_value,
                "unit": unit,
                "survey_date": as_of_date,
                "respondents": 0,
                "event_consensus": True,
                "provider": "Investing.com",
                "source_url": source_url,
                "previous": row.get("previous"),
            }
        )
    elif not expectation:
        expectation["event_consensus"] = False
    elif "event_consensus" not in expectation:
        expectation["event_consensus"] = False

    enriched["expectation"] = expectation
    return enriched, has_consensus


async def enrich_calendar_from_investing(
    events: list[dict[str, Any]],
    *,
    as_of_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    targets: dict[str, str] = {}
    for event in events:
        key = _event_source_key(event)
        if key is not None:
            targets[key] = _EVENT_URLS[key]

    async def load(key: str, url: str) -> tuple[str, str, list[dict[str, Any]] | None, str | None]:
        try:
            page = await _fetch_html(url, fetcher=fetcher)
            return key, url, _parse_rows(page), None
        except Exception as exc:  # noqa: BLE001 - every source page is independent
            return key, url, None, f"{type(exc).__name__}: {exc}"

    fetched = await asyncio.gather(*(load(key, url) for key, url in targets.items()))
    pages: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    errors: dict[str, str] = {}
    for key, url, rows, error in fetched:
        if rows is None:
            errors[key] = str(error or "unknown error")
        else:
            pages[key] = (url, rows)

    enriched: list[dict[str, Any]] = []
    matched = 0
    timed = 0
    consensus = 0
    for raw in events:
        event = dict(raw)
        key = _event_source_key(event)
        page = pages.get(key or "")
        if page is None:
            enriched.append(event)
            continue
        url, rows = page
        row = next((item for item in rows if item.get("date") == event.get("date")), None)
        if row is None:
            enriched.append(event)
            continue
        matched += 1
        event, has_consensus = _merge_row(
            event,
            row,
            source_url=url,
            as_of_date=as_of_date,
        )
        timed += 1
        if has_consensus:
            consensus += 1
        enriched.append(event)

    status = {
        "ready": timed > 0,
        "source": "Investing.com",
        "pages_requested": len(targets),
        "pages_ready": len(pages),
        "matched_events": matched,
        "timed_events": timed,
        "consensus_events": consensus,
        "errors": errors,
    }
    return enriched, status
