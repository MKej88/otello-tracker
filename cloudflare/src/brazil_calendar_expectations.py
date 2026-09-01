from __future__ import annotations

import re
import urllib.parse
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from brazil_dashboard import _decimal, _fetch_json, _float, _normalize

FOCUS_BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"
QUARTERLY_LOOKBACK_DAYS = 180

MONTHS = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "aug": 8,
    "set": 9,
    "sep": 9,
    "out": 10,
    "okt": 10,
    "nov": 11,
    "dez": 12,
    "des": 12,
}

COPOM_MEETINGS = {
    "2026-09-16": "R6/2026",
    "2026-11-04": "R7/2026",
    "2026-12-09": "R8/2026",
    "2027-01-27": "R1/2027",
}


def _latest_rows(payload: Any) -> list[dict[str, Any]]:
    values = payload.get("value") if isinstance(payload, dict) else None
    return [dict(row) for row in values if isinstance(row, dict)] if isinstance(values, list) else []


def _latest_matching(rows: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    matches = [row for row in rows if predicate(row) and _decimal(row.get("Mediana")) is not None]
    if not matches:
        return None
    matches.sort(key=lambda row: str(row.get("Data") or ""), reverse=True)
    return matches[0]


def _month_reference(value: Any) -> tuple[int, int] | None:
    raw = _normalize(value).replace(".", " ")
    year_match = re.search(r"\b(20\d{2})\b", raw)
    if not year_match:
        return None
    year = int(year_match.group(1))
    for name, month in MONTHS.items():
        if re.search(rf"\b{name}\w*\b", raw):
            return year, month
    slash = re.search(r"\b(0?[1-9]|1[0-2])\s*/\s*(20\d{2})\b", raw)
    if slash:
        return int(slash.group(2)), int(slash.group(1))
    iso = re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b", raw)
    if iso:
        return int(iso.group(1)), int(iso.group(2))
    return None


def _quarter_reference(value: Any) -> tuple[int, int] | None:
    raw = _normalize(value)
    year_match = re.search(r"\b(20\d{2})\b", raw)
    quarter_match = re.search(r"(?:q|t|trim(?:estre)?)\s*([1-4])", raw)
    if year_match and quarter_match:
        return int(year_match.group(1)), int(quarter_match.group(1))
    slash = re.search(r"\b([1-4])\s*/\s*(20\d{2})\b", raw)
    if slash:
        return int(slash.group(2)), int(slash.group(1))
    return None


def _event_month(event: dict[str, Any]) -> tuple[int, int] | None:
    return _month_reference(event.get("reference"))


def _event_quarter(event: dict[str, Any]) -> tuple[int, int] | None:
    return _quarter_reference(event.get("reference"))


def _quarter_reference_values(events: list[dict[str, Any]]) -> list[str]:
    references: set[str] = set()
    for event in events:
        if event.get("kind") != "gdp":
            continue
        target = _event_quarter(event)
        if target is None:
            continue
        year, quarter = target
        references.add(f"{quarter}/{year}")
    return sorted(references)


def _expectation(row: dict[str, Any], *, label: str, unit: str = "%") -> dict[str, Any]:
    return {
        "label": label,
        "value": _float(_decimal(row.get("Mediana"))),
        "unit": unit,
        "survey_date": str(row.get("Data") or "")[:10],
        "respondents": int(row.get("numeroRespondentes") or 0),
        "event_consensus": True,
        "provider": "BCB Focus",
    }


async def _fetch_endpoint(
    endpoint: str,
    *,
    start_date: str,
    end_date: str,
    indicators: list[str] | None = None,
    references: list[str] | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> list[dict[str, Any]]:
    filters = [f"Data ge '{start_date}'", f"Data le '{end_date}'"]
    if indicators:
        filters.append("(" + " or ".join(f"Indicador eq '{item}'" for item in indicators) + ")")
    if references:
        filters.append(
            "(" + " or ".join(f"DataReferencia eq '{item}'" for item in references) + ")"
        )
    params = {
        "$format": "json",
        "$top": "1200",
        "$orderby": "Data desc",
        "$filter": " and ".join(filters),
    }
    url = f"{FOCUS_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    payload = await _fetch_json(url, fetcher=fetcher)
    return _latest_rows(payload)


def _monthly_expectation(event: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = _event_month(event)
    if target is None:
        return None
    name = _normalize(event.get("name"))
    if name == "ipca":
        indicator = "ipca"
    elif name == "ipca-15":
        indicator = "ipca-15"
    elif event.get("kind") == "labor":
        indicator = "taxa de desocupacao"
    else:
        return None

    row = _latest_matching(
        rows,
        lambda item: _normalize(item.get("Indicador")) == indicator
        and _month_reference(item.get("DataReferencia")) == target,
    )
    if row is None:
        return None
    label_name = "Arbeidsledighet" if event.get("kind") == "labor" else str(event.get("name"))
    return _expectation(row, label=f"Focus {label_name} {target[1]:02d}/{str(target[0])[-2:]}")


def _quarterly_expectation(event: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if event.get("kind") != "gdp":
        return None
    target = _event_quarter(event)
    if target is None:
        return None
    row = _latest_matching(
        rows,
        lambda item: _normalize(item.get("Indicador")) in {"pib total", "pib"}
        and _quarter_reference(item.get("DataReferencia")) == target,
    )
    if row is None:
        return None
    return _expectation(row, label=f"Focus BNP Q{target[1]} {target[0]}")


def _selic_expectation(event: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if event.get("kind") != "copom":
        return None
    meeting = COPOM_MEETINGS.get(str(event.get("date") or ""))
    if meeting is None:
        return None
    row = _latest_matching(
        rows,
        lambda item: _normalize(item.get("Indicador")) == "selic"
        and str(item.get("Reuniao") or "").upper() == meeting,
    )
    if row is None:
        return None
    return _expectation(row, label=f"Focus Selic etter {meeting}")


async def enrich_calendar_expectations(
    events: list[dict[str, Any]],
    *,
    as_of_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    as_of = date.fromisoformat(as_of_date)
    start = (as_of - timedelta(days=21)).isoformat()
    quarterly_start = (as_of - timedelta(days=QUARTERLY_LOOKBACK_DAYS)).isoformat()
    quarterly_references = _quarter_reference_values(events)
    status: dict[str, Any] = {}

    monthly: list[dict[str, Any]] = []
    quarterly: list[dict[str, Any]] = []
    selic: list[dict[str, Any]] = []

    try:
        monthly = await _fetch_endpoint(
            "ExpectativaMercadoMensais",
            start_date=start,
            end_date=as_of_date,
            indicators=["IPCA", "IPCA-15", "Taxa de desocupação"],
            fetcher=fetcher,
        )
        status["monthly"] = {"ready": True, "rows": len(monthly)}
    except Exception as exc:
        status["monthly"] = {"ready": False, "error": f"{type(exc).__name__}: {exc}"}

    if quarterly_references:
        try:
            quarterly = await _fetch_endpoint(
                "ExpectativasMercadoTrimestrais",
                start_date=quarterly_start,
                end_date=as_of_date,
                indicators=["PIB Total"],
                references=quarterly_references,
                fetcher=fetcher,
            )
            status["quarterly"] = {
                "ready": True,
                "rows": len(quarterly),
                "references": quarterly_references,
                "lookback_days": QUARTERLY_LOOKBACK_DAYS,
            }
        except Exception as exc:
            status["quarterly"] = {
                "ready": False,
                "references": quarterly_references,
                "lookback_days": QUARTERLY_LOOKBACK_DAYS,
                "error": f"{type(exc).__name__}: {exc}",
            }
    else:
        status["quarterly"] = {
            "ready": True,
            "rows": 0,
            "references": [],
            "lookback_days": QUARTERLY_LOOKBACK_DAYS,
            "skipped": True,
        }

    try:
        selic = await _fetch_endpoint(
            "ExpectativasMercadoSelic",
            start_date=start,
            end_date=as_of_date,
            indicators=["Selic"],
            fetcher=fetcher,
        )
        status["selic"] = {"ready": True, "rows": len(selic)}
    except Exception as exc:
        status["selic"] = {"ready": False, "error": f"{type(exc).__name__}: {exc}"}

    enriched: list[dict[str, Any]] = []
    specific_count = 0
    for raw in events:
        event = dict(raw)
        specific = (
            _selic_expectation(event, selic)
            or _monthly_expectation(event, monthly)
            or _quarterly_expectation(event, quarterly)
        )
        if specific is not None:
            event["expectation"] = specific
            specific_count += 1
        enriched.append(event)

    status["specific_expectations"] = specific_count
    status["ready"] = specific_count > 0
    return enriched, status
