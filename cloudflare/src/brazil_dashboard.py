from __future__ import annotations

import asyncio
import json
import unicodedata
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from bounded_response import read_response_bytes

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
FOCUS_URL = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")

SERIES = {
    "selic": {"code": 432, "label": "Selic", "unit": "% p.a.", "mode": "level"},
    "ipca_12m": {"code": 13522, "label": "IPCA 12 mnd.", "unit": "%", "mode": "level"},
    "ibc_br": {"code": 24364, "label": "IBC-Br", "unit": "% m/m", "mode": "mom"},
    "ibc_services": {"code": 29605, "label": "IBC-Br tjenester", "unit": "% m/m", "mode": "mom"},
}


def _default_as_of_date(now: datetime | None = None) -> date:
    """Return the Brazilian calendar date used to cap local source data."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(BRAZIL_TZ).date()

IBGE_CALENDAR_URL = "https://www.ibge.gov.br/calendario/conjunturais.html"
BCB_COPOM_URL = "https://www.bcb.gov.br/controleinflacao/copom"
BCB_IBC_URL = "https://www.bcb.gov.br/estatisticas/calendario_indicadores"
BCB_FOCUS_URL = "https://dadosabertos.bcb.gov.br/dataset/expectativas-mercado"


def _normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    raw = str(value).strip().replace("%", "").replace(" ", "")
    if not raw:
        return None
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


async def _fetch_json(
    url: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> Any:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    response = await fetcher(
        url,
        headers={
            "Accept": "application/json,*/*;q=0.8",
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"HTTP {getattr(response, 'status', 'unknown')} for {url}")
    payload = await read_response_bytes(
        response,
        max_bytes=MAX_RESPONSE_BYTES,
        label="Brazil macro JSON",
    )
    return json.loads(payload.decode("utf-8-sig"))


def _parse_sgs_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("BCB SGS returnerte ikke en liste")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"BCB SGS-rad {index} er ikke et JSON-objekt")
        value = _decimal(item.get("valor"))
        raw_date_value = item.get("data")
        if value is None:
            raise ValueError(f"BCB SGS-rad {index} mangler gyldig verdi")
        if not isinstance(raw_date_value, str) or not raw_date_value.strip():
            raise ValueError(f"BCB SGS-rad {index} mangler gyldig dato")
        raw_date = raw_date_value.strip()
        try:
            parsed = datetime.strptime(raw_date, "%d/%m/%Y").date().isoformat()
        except ValueError as exc:
            raise ValueError(f"BCB SGS returnerte ugyldig dato: {raw_date!r}") from exc
        rows.append({"date": parsed, "value": value})
    if not rows:
        raise ValueError("BCB SGS returnerte ingen gyldige observasjoner")
    return sorted(rows, key=lambda row: str(row["date"]))


def _series_payload(key: str, rows: list[dict[str, Any]], *, source_url: str | None = None) -> dict[str, Any]:
    meta = SERIES[key]
    current = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    current_value = Decimal(str(current["value"]))
    previous_value = Decimal(str(previous["value"])) if previous else None
    mode = str(meta["mode"])
    if mode == "mom" and previous_value not in (None, Decimal("0")):
        display_value = (current_value / previous_value - Decimal("1")) * Decimal("100")
        previous_display = None
    else:
        display_value = current_value
        previous_display = previous_value
    change = None
    if mode == "level" and previous_value is not None:
        change = current_value - previous_value
    return {
        "key": key,
        "label": meta["label"],
        "unit": meta["unit"],
        "date": current["date"],
        "value": _float(display_value),
        "previous_value": _float(previous_display),
        "change": _float(change),
        "series": [
            {"date": str(row["date"]), "value": _float(Decimal(str(row["value"]))) }
            for row in rows
        ],
        "source": "Banco Central do Brasil / SGS",
        "source_url": source_url or SGS_URL.format(code=meta["code"]),
    }


async def _load_sgs_series(
    key: str,
    *,
    as_of_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    meta = SERIES[key]
    end = date.fromisoformat(as_of_date)
    # A single bounded window covers 18 monthly observations as well as the
    # more frequent Selic series without allowing observations after `end`.
    start = end - timedelta(days=570)
    params = urllib.parse.urlencode({
        "formato": "json",
        "dataInicial": start.strftime("%d/%m/%Y"),
        "dataFinal": end.strftime("%d/%m/%Y"),
    })
    url = f"{SGS_URL.format(code=meta['code'])}?{params}"
    payload = await _fetch_json(url, fetcher=fetcher)
    rows = [row for row in _parse_sgs_rows(payload) if str(row["date"]) <= as_of_date]
    if not rows:
        raise ValueError("BCB SGS mangler observasjoner på eller før valgt dato")
    return _series_payload(key, rows[-18:], source_url=url)


def _focus_indicator_key(value: Any) -> str | None:
    normalized = _normalize(value)
    if normalized == "ipca":
        return "ipca"
    if normalized == "selic":
        return "selic"
    if normalized in {"pib total", "pib"}:
        return "gdp"
    if normalized in {"cambio", "taxa de cambio"}:
        return "usd_brl"
    return None


def _focus_year(value: Any) -> int | None:
    raw = str(value or "").strip()
    if len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return None


def parse_focus_rows(payload: Any, *, as_of_date: str) -> dict[str, Any]:
    values = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        raise ValueError("BCB Focus returnerte ikke value-listen")
    as_of = date.fromisoformat(as_of_date)
    wanted_years = {as_of.year, as_of.year + 1}
    candidates: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for raw in values:
        if not isinstance(raw, dict):
            continue
        survey_date = str(raw.get("Data") or "")[:10]
        if survey_date and survey_date > as_of_date:
            continue
        key = _focus_indicator_key(raw.get("Indicador"))
        year = _focus_year(raw.get("DataReferencia"))
        if key is None or year not in wanted_years:
            continue
        median = _decimal(raw.get("Mediana"))
        if median is None:
            continue
        candidates.setdefault((key, year), []).append(raw)

    result: dict[str, Any] = {}
    for (key, year), rows in candidates.items():
        rows.sort(key=lambda item: str(item.get("Data") or ""), reverse=True)
        latest = rows[0]
        result.setdefault(key, {})[str(year)] = {
            "median": _float(_decimal(latest.get("Mediana"))),
            "mean": _float(_decimal(latest.get("Media"))),
            "min": _float(_decimal(latest.get("Minimo"))),
            "max": _float(_decimal(latest.get("Maximo"))),
            "respondents": int(latest.get("numeroRespondentes") or 0),
            "survey_date": str(latest.get("Data") or "")[:10],
        }
    return result


async def _load_focus(
    as_of_date: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    as_of = date.fromisoformat(as_of_date)
    start = (as_of - timedelta(days=21)).isoformat()
    indicators = ["IPCA", "Selic", "PIB Total", "Câmbio"]
    indicator_filter = " or ".join(f"Indicador eq '{item}'" for item in indicators)
    params = {
        "$format": "json",
        "$top": "800",
        "$orderby": "Data desc",
        "$filter": f"Data ge '{start}' and Data le '{as_of_date}' and ({indicator_filter})",
    }
    url = FOCUS_URL + "?" + urllib.parse.urlencode(params)
    payload = await _fetch_json(url, fetcher=fetcher)
    values = parse_focus_rows(payload, as_of_date=as_of_date)
    return {
        "ready": bool(values),
        "values": values,
        "source": "Banco Central do Brasil / Focus",
        "source_url": BCB_FOCUS_URL,
        "note": "Focus er årsforventninger, ikke konsensus for den enkelte publisering.",
    }


def _impact(kind: str) -> tuple[str, str]:
    mapping = {
        "copom": (
            "Høy",
            "Lavere rente/rentebane er normalt positivt for Bemobis multippel. Høyere rente er negativt.",
        ),
        "inflation": (
            "Høy",
            "Lavere inflasjon enn ventet øker rommet for rentekutt og er normalt positivt for verdsettelsen.",
        ),
        "gdp": (
            "Middels–høy",
            "Sterkere aktivitet støtter Bemobis etterspørsel, men svært sterk vekst kan samtidig forsinke rentekutt.",
        ),
        "services": (
            "Middels–høy",
            "Tjenestevekst er en direkte temperaturmåler på økonomien Bemobi opererer i. Sterkere er normalt positivt for drift.",
        ),
        "retail": (
            "Middels",
            "Sterkere konsum er positivt for betalings- og digitale tjenestevolumer, men kan holde rentene høyere lenger.",
        ),
        "activity": (
            "Middels–høy",
            "IBC-Br gir et raskt signal om brasiliansk aktivitet. Moderat bedring er positivt for Bemobi.",
        ),
        "labor": (
            "Middels",
            "Bedre arbeidsmarked støtter konsum og betalingsvolumer. Et for stramt arbeidsmarked kan være inflasjonært.",
        ),
    }
    return mapping[kind]


def _calendar_seed() -> list[dict[str, Any]]:
    # Offisielle 2026/2027-datoer publisert av IBGE og BCB. Listen er bevisst
    # begrenset til hendelser med klar relevans for Bemobi/renter/BRL.
    raw = [
        ("2026-09-01", "BNP Q2", "gdp", "IBGE", IBGE_CALENDAR_URL, "2026 Q2"),
        ("2026-09-10", "Tjenesteaktivitet (PMS)", "services", "IBGE", IBGE_CALENDAR_URL, "jul. 2026"),
        ("2026-09-11", "IPCA", "inflation", "IBGE", IBGE_CALENDAR_URL, "aug. 2026"),
        ("2026-09-15", "Detaljhandel (PMC)", "retail", "IBGE", IBGE_CALENDAR_URL, "jul. 2026"),
        ("2026-09-16", "Copom rentebeslutning", "copom", "BCB", BCB_COPOM_URL, None),
        ("2026-09-16", "IBC-Br", "activity", "BCB", BCB_IBC_URL, "jul. 2026"),
        ("2026-09-25", "IPCA-15", "inflation", "IBGE", IBGE_CALENDAR_URL, "sep. 2026"),
        ("2026-09-29", "Arbeidsledighet (PNAD)", "labor", "IBGE", IBGE_CALENDAR_URL, "aug. 2026"),
        ("2026-10-09", "IPCA", "inflation", "IBGE", IBGE_CALENDAR_URL, "sep. 2026"),
        ("2026-10-14", "Tjenesteaktivitet (PMS)", "services", "IBGE", IBGE_CALENDAR_URL, "aug. 2026"),
        ("2026-10-15", "Detaljhandel (PMC)", "retail", "IBGE", IBGE_CALENDAR_URL, "aug. 2026"),
        ("2026-10-16", "IBC-Br", "activity", "BCB", BCB_IBC_URL, "aug. 2026"),
        ("2026-10-23", "IPCA-15", "inflation", "IBGE", IBGE_CALENDAR_URL, "okt. 2026"),
        ("2026-10-30", "Arbeidsledighet (PNAD)", "labor", "IBGE", IBGE_CALENDAR_URL, "sep. 2026"),
        ("2026-11-04", "Copom rentebeslutning", "copom", "BCB", BCB_COPOM_URL, None),
        ("2026-11-11", "Tjenesteaktivitet (PMS)", "services", "IBGE", IBGE_CALENDAR_URL, "sep. 2026"),
        ("2026-11-12", "IPCA", "inflation", "IBGE", IBGE_CALENDAR_URL, "okt. 2026"),
        ("2026-11-13", "Detaljhandel (PMC)", "retail", "IBGE", IBGE_CALENDAR_URL, "sep. 2026"),
        ("2026-11-16", "IBC-Br", "activity", "BCB", BCB_IBC_URL, "sep. 2026"),
        ("2026-11-27", "Arbeidsledighet (PNAD)", "labor", "IBGE", IBGE_CALENDAR_URL, "okt. 2026"),
        ("2026-12-02", "BNP Q3", "gdp", "IBGE", IBGE_CALENDAR_URL, "2026 Q3"),
        ("2026-12-08", "Detaljhandel (PMC)", "retail", "IBGE", IBGE_CALENDAR_URL, "okt. 2026"),
        ("2026-12-09", "Copom rentebeslutning", "copom", "BCB", BCB_COPOM_URL, None),
        ("2026-12-10", "Tjenesteaktivitet (PMS)", "services", "IBGE", IBGE_CALENDAR_URL, "okt. 2026"),
        ("2026-12-11", "IPCA", "inflation", "IBGE", IBGE_CALENDAR_URL, "nov. 2026"),
        ("2026-12-11", "IBC-Br", "activity", "BCB", BCB_IBC_URL, "okt. 2026"),
        ("2026-12-23", "IPCA-15", "inflation", "IBGE", IBGE_CALENDAR_URL, "des. 2026"),
        ("2026-12-29", "Arbeidsledighet (PNAD)", "labor", "IBGE", IBGE_CALENDAR_URL, "nov. 2026"),
        ("2027-01-12", "IPCA", "inflation", "IBGE", IBGE_CALENDAR_URL, "des. 2026"),
        ("2027-01-13", "Tjenesteaktivitet (PMS)", "services", "IBGE", IBGE_CALENDAR_URL, "nov. 2026"),
        ("2027-01-15", "Detaljhandel (PMC)", "retail", "IBGE", IBGE_CALENDAR_URL, "nov. 2026"),
        ("2027-01-18", "IBC-Br", "activity", "BCB", BCB_IBC_URL, "nov. 2026"),
        ("2027-01-27", "Copom rentebeslutning", "copom", "BCB", BCB_COPOM_URL, None),
        ("2027-01-29", "Arbeidsledighet (PNAD)", "labor", "IBGE", IBGE_CALENDAR_URL, "des. 2026"),
        ("2027-02-16", "Tjenesteaktivitet (PMS)", "services", "IBGE", IBGE_CALENDAR_URL, "des. 2026"),
        ("2027-02-17", "Detaljhandel (PMC)", "retail", "IBGE", IBGE_CALENDAR_URL, "des. 2026"),
        ("2027-02-18", "IBC-Br", "activity", "BCB", BCB_IBC_URL, "des. 2026"),
    ]
    result = []
    for event_date, name, kind, source, source_url, reference in raw:
        importance, impact = _impact(kind)
        result.append({
            "date": event_date,
            "name": name,
            "kind": kind,
            "source": source,
            "source_url": source_url,
            "reference": reference,
            "importance": importance,
            "bemobi_impact": impact,
        })
    return result


def _next_weekday(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _rolling_calendar(start: date, end: date) -> list[dict[str, Any]]:
    """Provide a clearly labelled rolling preview beyond the published seed.

    IBGE and BCB publish exact release dates incrementally. Keeping a recurring
    preview prevents the dashboard from going permanently blank between seed
    updates; these rows deliberately do not claim to be confirmed dates and
    link to the maintained official calendars.
    """
    first_month = date(start.year, start.month, 1)
    month = first_month
    rows: list[dict[str, Any]] = []
    templates = [
        (10, "IPCA", "inflation", "IBGE", IBGE_CALENDAR_URL),
        (12, "Tjenesteaktivitet (PMS)", "services", "IBGE", IBGE_CALENDAR_URL),
        (14, "Detaljhandel (PMC)", "retail", "IBGE", IBGE_CALENDAR_URL),
        (16, "IBC-Br", "activity", "BCB", BCB_IBC_URL),
        (25, "IPCA-15", "inflation", "IBGE", IBGE_CALENDAR_URL),
        (28, "Arbeidsledighet (PNAD)", "labor", "IBGE", IBGE_CALENDAR_URL),
    ]
    while month <= end:
        for day_number, name, kind, source, source_url in templates:
            event_day = _next_weekday(date(month.year, month.month, day_number))
            if not (start <= event_day <= end):
                continue
            importance, impact = _impact(kind)
            rows.append({
                "date": event_day.isoformat(),
                "name": name,
                "kind": kind,
                "source": source,
                "source_url": source_url,
                "reference": None,
                "importance": importance,
                "bemobi_impact": impact,
                "date_status": "estimated",
            })
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return rows


def _focus_expectation_for_event(event: dict[str, Any], focus: dict[str, Any], year: int) -> dict[str, Any] | None:
    key = {
        "copom": "selic",
        "inflation": "ipca",
        "gdp": "gdp",
        "services": "gdp",
        "retail": "gdp",
        "activity": "gdp",
    }.get(str(event.get("kind")))
    if key is None:
        return None
    row = (focus.get(key) or {}).get(str(year))
    if not isinstance(row, dict) or row.get("median") is None:
        return None
    unit = "%" if key != "usd_brl" else "BRL/USD"
    label = {
        "selic": f"Focus {year} Selic (årsslutt)",
        "ipca": f"Focus {year} IPCA (år)",
        "gdp": f"Focus {year} BNP (år, proxy)",
    }[key]
    return {
        "label": label,
        "value": row["median"],
        "unit": unit,
        "survey_date": row.get("survey_date"),
        "event_consensus": False,
    }


def calendar_events(*, as_of_date: str, focus: dict[str, Any]) -> list[dict[str, Any]]:
    start = date.fromisoformat(as_of_date)
    horizon = start + timedelta(days=190)
    events = []
    seeded = _calendar_seed()
    seed_end = max(date.fromisoformat(str(item["date"])) for item in seeded)
    candidates = seeded
    if horizon > seed_end:
        candidates += _rolling_calendar(seed_end + timedelta(days=1), horizon)
    for raw in candidates:
        event_day = date.fromisoformat(str(raw["date"]))
        if not (start <= event_day <= horizon):
            continue
        event = dict(raw)
        event["expectation"] = _focus_expectation_for_event(event, focus, event_day.year)
        events.append(event)
    events.sort(key=lambda item: (str(item["date"]), str(item["name"])))
    return events


async def _brl_nok(repository, as_of_date: str) -> dict[str, Any]:
    row = await repository.first(
        """
        SELECT substr(fr.observed_at,1,10) AS rate_date, fr.rate, s.code AS source_code
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.base_currency='BRL' AND fr.quote_currency='NOK'
          AND substr(fr.observed_at,1,10)<=?
        ORDER BY substr(fr.observed_at,1,10) DESC,
                 CASE s.code WHEN 'NORGES_BANK' THEN 0 WHEN 'ECB' THEN 1 ELSE 5 END,
                 fr.observed_at DESC, fr.id DESC
        LIMIT 1
        """,
        (as_of_date,),
    )
    if row is None:
        return {"ready": False, "reason": "missing_brl_nok"}
    current = _decimal(row.get("rate"))
    if current is None or current <= 0:
        return {"ready": False, "reason": "invalid_brl_nok"}
    quote_date = date.fromisoformat(str(row.get("rate_date")))
    floor = (quote_date - timedelta(days=35)).isoformat()
    previous = await repository.first(
        """
        SELECT substr(fr.observed_at,1,10) AS rate_date, fr.rate
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.base_currency='BRL' AND fr.quote_currency='NOK'
          AND substr(fr.observed_at,1,10)<=? AND substr(fr.observed_at,1,10)>=?
        ORDER BY substr(fr.observed_at,1,10) ASC,
                 CASE s.code WHEN 'NORGES_BANK' THEN 0 WHEN 'ECB' THEN 1 ELSE 5 END,
                 fr.observed_at ASC, fr.id ASC
        LIMIT 1
        """,
        ((quote_date - timedelta(days=28)).isoformat(), floor),
    )
    previous_rate = _decimal(previous.get("rate")) if previous else None
    change_pct = None
    if previous_rate not in (None, Decimal("0")):
        change_pct = (current / previous_rate - Decimal("1")) * Decimal("100")
    history_rows = await repository.all(
        """
        SELECT rate_date, rate
        FROM (
            SELECT substr(fr.observed_at,1,10) AS rate_date, fr.rate,
                   ROW_NUMBER() OVER (
                       PARTITION BY substr(fr.observed_at,1,10)
                       ORDER BY CASE s.code
                                    WHEN 'NORGES_BANK' THEN 0
                                    WHEN 'ECB' THEN 1
                                    ELSE 5
                                END,
                                fr.observed_at DESC, fr.id DESC
                   ) AS source_rank
            FROM fx_rates fr
            JOIN sources s ON s.id=fr.source_id
            WHERE fr.base_currency='BRL' AND fr.quote_currency='NOK'
              AND substr(fr.observed_at,1,10)<=?
              AND substr(fr.observed_at,1,10)>=?
        )
        WHERE source_rank=1
        ORDER BY rate_date DESC
        LIMIT 18
        """,
        (quote_date.isoformat(), floor),
    )
    series = [
        {"date": str(item.get("rate_date") or ""), "value": _float(rate)}
        for item in reversed(history_rows)
        if (rate := _decimal(item.get("rate"))) is not None and rate > 0
    ]
    return {
        "ready": True,
        "key": "brl_nok",
        "label": "BRL/NOK",
        "unit": "NOK per BRL",
        "date": str(row.get("rate_date") or ""),
        "value": _float(current),
        "change_1m_pct": _float(change_pct),
        "series": series,
        "source": "Norges Bank" if row.get("source_code") == "NORGES_BANK" else str(row.get("source_code") or "FX"),
        "source_url": "https://data.norges-bank.no/api/data/EXR/B.BRL.NOK.SP",
        "bemobi_impact": "Sterkere BRL mot NOK øker Otellos Bemobi-verdi direkte målt i NOK.",
    }


def _metric_signal(key: str, metric: dict[str, Any], focus: dict[str, Any], year: int) -> dict[str, str]:
    value = metric.get("value")
    if value is None:
        return {"tone": "neutral", "label": "Datagrunnlag mangler"}
    number = Decimal(str(value))
    if key == "brl_nok":
        change = metric.get("change_1m_pct")
        if change is None:
            return {"tone": "neutral", "label": "Direkte NAV-driver"}
        return {
            "tone": "positive" if Decimal(str(change)) >= 0 else "negative",
            "label": "Positiv NAV-valuta" if Decimal(str(change)) >= 0 else "Negativ NAV-valuta",
        }
    if key == "selic":
        expected = ((focus.get("selic") or {}).get(str(year)) or {}).get("median")
        if expected is not None and number > Decimal(str(expected)):
            return {"tone": "positive", "label": "Focus priser lavere rente"}
        return {"tone": "neutral", "label": "Følg rentebanen"}
    if key == "ipca_12m":
        expected = ((focus.get("ipca") or {}).get(str(year)) or {}).get("median")
        if expected is not None and number > Decimal(str(expected)):
            return {"tone": "negative", "label": "Inflasjon over årsforventning"}
        return {"tone": "positive", "label": "Inflasjon støtter rentekutt"}
    if key in {"ibc_br", "ibc_services"}:
        if number > Decimal("0"):
            return {"tone": "positive", "label": "Aktiviteten vokser"}
        if number < Decimal("0"):
            return {"tone": "negative", "label": "Aktiviteten faller"}
    return {"tone": "neutral", "label": "Nøytral"}


async def brazil_dashboard(
    repository,
    *,
    as_of_date: str | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    target = date.fromisoformat(as_of_date) if as_of_date else _default_as_of_date()
    target_date = target.isoformat()

    tasks = [_load_sgs_series(key, as_of_date=target_date, fetcher=fetcher) for key in SERIES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    metrics: dict[str, Any] = {}
    source_status: dict[str, Any] = {}
    for key, result in zip(SERIES, results):
        if isinstance(result, Exception):
            source_status[key] = {"ready": False, "error": f"{type(result).__name__}: {result}"}
        else:
            metrics[key] = result
            source_status[key] = {"ready": True, "date": result.get("date")}

    try:
        focus_result = await _load_focus(target_date, fetcher=fetcher)
        focus = focus_result.get("values") or {}
        source_status["focus"] = {"ready": bool(focus), "source": focus_result.get("source")}
    except Exception as exc:
        focus_result = {
            "ready": False,
            "values": {},
            "source": "Banco Central do Brasil / Focus",
            "source_url": BCB_FOCUS_URL,
            "note": "Focus kunne ikke hentes. De øvrige offisielle makrotallene vises fortsatt.",
        }
        focus = {}
        source_status["focus"] = {"ready": False, "error": f"{type(exc).__name__}: {exc}"}

    fx = await _brl_nok(repository, target_date)
    if fx.get("ready"):
        metrics["brl_nok"] = fx
    source_status["brl_nok"] = {"ready": bool(fx.get("ready")), "date": fx.get("date"), "reason": fx.get("reason")}

    for key, metric in metrics.items():
        metric["signal"] = _metric_signal(key, metric, focus, target.year)
        if key == "selic":
            metric["bemobi_impact"] = "Lavere Selic reduserer avkastningskravet og kan gi multippel-ekspansjon i BMOB3."
        elif key == "ipca_12m":
            metric["bemobi_impact"] = "Lavere inflasjon gir mer rom for rentekutt og er normalt positivt for brasilianske vekstaksjer."
        elif key == "ibc_br":
            metric["bemobi_impact"] = "Bedre bred økonomisk aktivitet støtter volum og etterspørsel, men for sterk vekst kan holde rentene høye."
        elif key == "ibc_services":
            metric["bemobi_impact"] = "Tjenesteaktivitet er særlig relevant for Bemobis digitale tjeneste- og betalingsøkosystem."

    calendar = calendar_events(as_of_date=target_date, focus=focus)
    return {
        "ready": bool(metrics),
        "as_of_date": target_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "metrics": metrics,
        "focus": focus_result,
        "calendar": calendar,
        "calendar_note": "Bekreftede datoer kommer fra IBGE/BCB. Rader merket estimated er en rullerende forhåndsvisning og må bekreftes i den lenkede offisielle kalenderen. Forventning-feltet bruker BCB Focus som års-/retningsproxy og er ikke konsensus for den enkelte publisering.",
        "source_status": source_status,
        "sources": [
            {"name": "Banco Central do Brasil – SGS", "url": "https://dadosabertos.bcb.gov.br/"},
            {"name": "Banco Central do Brasil – Focus", "url": BCB_FOCUS_URL},
            {"name": "Banco Central do Brasil – kalender", "url": BCB_COPOM_URL},
            {"name": "IBGE – indikator-kalender", "url": IBGE_CALENDAR_URL},
        ],
    }
