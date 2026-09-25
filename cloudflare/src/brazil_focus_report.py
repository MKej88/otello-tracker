"""Bounded, independently hosted fallback to BCB's weekly published report."""
from __future__ import annotations

import asyncio
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from bounded_response import read_response_bytes

REPORT_ROOT = "https://www.bcb.gov.br/content/focus/focus/"
STATE_KEY = "brazil_focus_published_report_v1"
MONTHS = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)
LABELS = {"IPCA (": "ipca", "PIB Total (": "gdp", "Câmbio (": "usd_brl", "Selic (": "selic"}


def report_candidates(as_of_date: str) -> list[date]:
    # A Friday survey is normally published the following Monday. Never probe
    # this week's Friday prematurely, including in historical dashboard queries.
    target = date.fromisoformat(as_of_date)
    monday = target - timedelta(days=target.weekday())
    friday = monday - timedelta(days=3)
    # Thursday covers Friday holidays. Bound both network and PDF parsing work.
    return [friday - timedelta(days=7 * week + offset) for week in range(3) for offset in (0, 1)]


def parse_report_text(text: str, *, reference_date: str, as_of_date: str) -> dict[str, Any]:
    """Read the aggregate Hoje columns, never the nearby 5-business-day sample.

    Fail closed if the four-year annual table or the report layout changes.
    pypdf's layout mode separates adjacent numeric cells in Selic rows.
    """
    reference = date.fromisoformat(reference_date)
    target = date.fromisoformat(as_of_date)
    publication = reference + timedelta(days=7 - reference.weekday())
    if publication > target:
        raise ValueError("Focus-rapporten var ikke publisert på valgt dato")
    heading = re.search(r"\b(\d{1,2}) de (\w+) de (20\d{2})\b", text)
    if not heading or heading.group(2) not in MONTHS:
        raise ValueError("Focus PDF mangler rapportdato")
    actual = date(int(heading[3]), MONTHS.index(heading[2]) + 1, int(heading[1]))
    if actual != reference:
        raise ValueError("Focus PDF-dato stemmer ikke med rapportlenken")
    years_match = re.search(r"^\s*(20\d{2})\s+(20\d{2})\s+(20\d{2})\s+(20\d{2})\s*$", text, re.M)
    if not years_match:
        raise ValueError("Focus PDF mangler entydig årsoverskrift")
    years = [int(x) for x in years_match.groups()]
    if years != list(range(years[0], years[0] + 4)) or years[0] != target.year:
        raise ValueError("Focus PDF har feil prognoseår")
    header = next((line for line in text.splitlines() if "Mediana - Agregado" in line), "")
    if len(re.findall(r"\bHoje\b", header)) != 4:
        raise ValueError("Focus PDF har ukjent kolonnestruktur")
    values: dict[str, Any] = {}
    for line in text.splitlines():
        for label, key in LABELS.items():
            if not line.strip().startswith(label):
                continue
            # First two year groups: 4 decimal values each (4w, 1w, today,
            # 5-day sample). Later years: 3 each. Counts/trend markers are integers.
            numbers = re.findall(r"-?\d+,\d{2}(?!\d)", line)
            if len(numbers) != 14 or key in values:
                raise ValueError("Focus PDF har uventet eller duplisert indikatorrad")
            values[key] = {
                str(years[i]): {
                    "median": float(numbers[index].replace(",", ".")),
                    "survey_date": reference_date,
                    "source_url": f"{REPORT_ROOT}R{reference:%Y%m%d}.pdf",
                    "data_source": "BCB_PUBLISHED_FOCUS_REPORT",
                }
                for i, index in enumerate((2, 6))
            }
    if set(values) != set(LABELS.values()):
        raise ValueError("Focus PDF mangler nødvendige indikatorer")
    return {
        "ready": True, "values": values,
        "source": "Banco Central do Brasil / Focus – publisert rapport",
        "source_url": f"{REPORT_ROOT}R{reference:%Y%m%d}.pdf",
        "data_source": "BCB_PUBLISHED_FOCUS_REPORT",
        "fallback": True,
        "publication_date": publication.isoformat(),
        "note": "Oppdatert fra sentralbankens publiserte Focus-rapport.",
    }


def parse_report_pdf(payload: bytes, **kwargs: Any) -> dict[str, Any]:
    from pypdf import PdfReader

    if not payload.startswith(b"%PDF-"):
        raise ValueError("Focus svarte ikke med PDF")
    reader = PdfReader(io.BytesIO(payload))
    if not 1 <= len(reader.pages) <= 4:
        raise ValueError("Focus PDF har uventet sideantall")
    return parse_report_text(reader.pages[0].extract_text(extraction_mode="layout"), **kwargs)


async def load_published_focus(repository, *, as_of_date: str, fetcher=None) -> dict[str, Any]:
    """Cache successes and failures for one hour, scoped to the requested date."""
    now = datetime.now(UTC)
    cached: dict[str, Any] = {}
    try:
        row = await repository.first("SELECT value FROM runtime_state WHERE key = ?", (STATE_KEY,))
        cached = json.loads(row["value"]) if row else {}
        checked = datetime.fromisoformat(cached.get("checked_at", ""))
        if cached.get("as_of_date") == as_of_date and timedelta(0) <= now - checked < timedelta(hours=1):
            return cached["result"]
    except Exception:
        pass  # Cache failure must not prevent fetching the official report.
    if fetcher is None:
        from workers import fetch
        fetcher = fetch

    errors: list[str] = []
    result: dict[str, Any] = {"ready": False, "values": {}}
    for reference in report_candidates(as_of_date):
        url = f"{REPORT_ROOT}R{reference:%Y%m%d}.pdf"
        try:
            async def download() -> bytes:
                response = await fetcher(url, headers={"Accept": "application/pdf"})
                if not response.ok:
                    raise ValueError(f"Focus PDF HTTP {response.status}")
                return await read_response_bytes(response, max_bytes=2 * 1024 * 1024, label="Focus PDF")
            payload = await asyncio.wait_for(download(), timeout=8)
            result = parse_report_pdf(payload, reference_date=reference.isoformat(), as_of_date=as_of_date)
            break
        except Exception as exc:
            errors.append(f"{reference}: {type(exc).__name__}: {exc}")
    result["report_errors"] = errors
    try:
        await repository.run(
            "INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (STATE_KEY, json.dumps({"checked_at": now.isoformat(), "as_of_date": as_of_date, "result": result}), now.isoformat()),
        )
    except Exception as exc:
        result["cache_error"] = f"{type(exc).__name__}: {exc}"
    return result


async def supplement_focus(repository, live: Any, *, as_of_date: str, fetcher=None) -> dict[str, Any]:
    """Use the newest point from live API/report; the last-good cache follows later."""
    from brazil_dashboard import FOCUS_REQUIRED_KEYS

    live = dict(live) if isinstance(live, dict) else {}
    values = live.get("values") or {}
    newest_report = report_candidates(as_of_date)[0].isoformat()
    year = date.fromisoformat(as_of_date).year
    if all(
        (point := values.get(key, {}).get(str(y), {})).get("median") is not None
        and str(point.get("survey_date") or "") >= newest_report
        for key in FOCUS_REQUIRED_KEYS for y in (year, year + 1)
    ):
        return live
    try:
        report = await asyncio.wait_for(
            load_published_focus(repository, as_of_date=as_of_date, fetcher=fetcher), timeout=20
        )
    except Exception as exc:
        live["report_errors"] = [f"{type(exc).__name__}: {exc}"]
        return live
    if not report.get("ready"):
        live["report_errors"] = report.get("report_errors", [])
        return live
    merged = {key: {year: dict(point) for year, point in by_year.items()} for key, by_year in values.items()}
    replaced = False
    for key, by_year in report["values"].items():
        for year, point in by_year.items():
            old = merged.setdefault(key, {}).get(year, {})
            if old.get("median") is None or str(old.get("survey_date") or "") < point["survey_date"]:
                merged[key][year] = point
                replaced = True
    if not replaced:
        return live
    return {**live, **report, "values": merged, "partial": False}
