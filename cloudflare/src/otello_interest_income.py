from __future__ import annotations

import io
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

from pypdf import PdfReader

try:
    from .newsweb_client import fetch_attachment
except ImportError:
    from newsweb_client import fetch_attachment

INTEREST_PARSER_VERSION = "otello-interest-income-v1"
ATTRIBUTION_POLICY = "REPORTED_HALF_YEAR_INTEREST_PRORATED_BY_DAY_USING_REPORTED_PERIOD_FX"

_SPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
_PERIOD_RE = re.compile(r"^(1H|2H)(\d{2})$")
_NEWSWEB_REPORT_RE = re.compile(r"^newsweb-report:(\d+):(\d+)$")


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\u00a0", " ").splitlines():
        line = _SPACE_RE.sub(" ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _number(token: str) -> Decimal:
    raw = token.strip().replace(",", "")
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Ugyldig rapporttall: {token!r}") from exc
    return -value if negative else value


def _period_bounds(source_period: str) -> tuple[date, date, int, tuple[str, str]]:
    match = _PERIOD_RE.fullmatch(source_period.strip().upper())
    if match is None:
        raise ValueError(f"Ikke støttet renteperiode: {source_period}")
    half, short_year = match.groups()
    year = 2000 + int(short_year)
    if half == "1H":
        start = date(year, 1, 1)
        end = date(year, 6, 30)
        months = ("March", "June")
    else:
        start = date(year, 7, 1)
        end = date(year, 12, 31)
        months = ("September", "December")
    return start, end, (end - start).days + 1, months


def _interest_k(lines: list[str]) -> Decimal | None:
    label = re.compile(r"^interest income received\b", re.I)
    for index, line in enumerate(lines):
        match = label.search(line)
        if match is None:
            continue
        candidates = _NUMBER_RE.findall(line[match.end() :])
        if not candidates and index + 1 < len(lines):
            candidates = _NUMBER_RE.findall(lines[index + 1])
        if candidates:
            return _number(candidates[0])
    return None


def _usd_nok_rates(
    lines: list[str],
    *,
    year: int,
    months: tuple[str, str],
) -> dict[str, Decimal]:
    section_indexes = [
        index
        for index, line in enumerate(lines)
        if re.search(r"\bUSD\s*:\s*NOK\b", line, re.I)
    ]
    rates: dict[str, Decimal] = {}
    for section in section_indexes:
        limit = min(section + 18, len(lines))
        for index in range(section + 1, limit):
            window = " ".join(lines[index : min(index + 3, limit)])
            for month in months:
                if month in rates:
                    continue
                phrase = re.search(
                    rf"For the {month} period\s+{year}\s*:?\s*(.*)",
                    window,
                    re.I,
                )
                if phrase is None:
                    continue
                decimals = re.findall(r"\b\d{1,2}\.\d{3,6}\b", phrase.group(1))
                for token in decimals:
                    value = Decimal(token)
                    if Decimal("5") <= value <= Decimal("20"):
                        rates[month] = value
                        break
        if all(month in rates for month in months):
            break
    return rates


def parse_report_interest_income(text: str, source_period: str) -> dict[str, Any]:
    """Extract exact cash interest and Otello's own period USD/NOK rates from a half-year report."""
    try:
        start, end, period_days, months = _period_bounds(source_period)
    except ValueError as exc:
        return {
            "valid": False,
            "parser_version": INTEREST_PARSER_VERSION,
            "issues": [str(exc)],
            "facts": {},
        }

    lines = _clean_lines(text)
    interest_k = _interest_k(lines)
    rates = _usd_nok_rates(lines, year=end.year, months=months)
    issues: list[str] = []
    if interest_k is None:
        issues.append("missing_interest_income_received")
    elif interest_k < 0:
        issues.append("negative_interest_income_received")
    for month in months:
        if month not in rates:
            issues.append(f"missing_usd_nok_{month.lower()}_{end.year}")
    if issues:
        return {
            "valid": False,
            "parser_version": INTEREST_PARSER_VERSION,
            "issues": issues,
            "facts": {},
        }

    if source_period.upper().startswith("1H"):
        segment_dates = ((date(end.year, 1, 1), date(end.year, 3, 31)), (date(end.year, 4, 1), end))
    else:
        segment_dates = ((date(end.year, 7, 1), date(end.year, 9, 30)), (date(end.year, 10, 1), end))

    fx_segments = []
    for month, (segment_start, segment_end) in zip(months, segment_dates, strict=True):
        fx_segments.append(
            {
                "start_date": segment_start.isoformat(),
                "end_date": segment_end.isoformat(),
                "usd_nok": format(rates[month], "f"),
                "source_label": f"For the {month} period {end.year}",
            }
        )

    amount_usd = interest_k * Decimal("1000")
    return {
        "valid": True,
        "parser_version": INTEREST_PARSER_VERSION,
        "issues": [],
        "facts": {
            "source_period": source_period.upper(),
            "source_period_start": start.isoformat(),
            "source_period_end": end.isoformat(),
            "period_days": period_days,
            "amount_usd": format(amount_usd, "f"),
            "source_measure": "interest income received",
            "fx_segments": fx_segments,
        },
    }


def _pdf_text(payload: bytes) -> str:
    if not payload.startswith(b"%PDF"):
        raise ValueError("Otello-renteparser mottok ikke en PDF")
    reader = PdfReader(io.BytesIO(payload))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        raise ValueError("Otello-renteparser fant ingen tekst i PDF-en")
    return text


async def _default_report_text_loader(message_id: int, attachment_id: int) -> str:
    return _pdf_text(await fetch_attachment(message_id, attachment_id))


async def _existing_periods(repository) -> set[str]:
    rows = await repository.all(
        """
        SELECT metadata_json
        FROM source_documents
        WHERE document_type='ECONOMIC_NAV_INTEREST_INCOME_ANCHOR'
        """
    )
    periods: set[str] = set()
    for row in rows:
        try:
            metadata = json.loads(str(row.get("metadata_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        source_period = str(metadata.get("source_period") or "").strip().upper()
        if source_period:
            periods.add(source_period)
    return periods


async def sync_interest_income_anchors_from_report_result(
    repository,
    report_result: dict[str, Any] | None,
    *,
    report_text_loader: Callable[[int, int], Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """Create idempotent source-backed interest anchors for newly auto-applied Otello reports."""
    results = (report_result or {}).get("results") or []
    if not isinstance(results, list) or not results:
        return {"status": "ok", "candidates": 0, "written": 0, "existing": 0, "errors": []}

    loader = report_text_loader or _default_report_text_loader
    existing_periods = await _existing_periods(repository)
    written = 0
    existing = 0
    errors: list[dict[str, Any]] = []
    processed: list[dict[str, Any]] = []

    for item in results:
        if not isinstance(item, dict) or item.get("status") != "applied":
            continue
        facts = item.get("facts") or {}
        source_period = str(facts.get("source_period") or "").strip().upper()
        if _PERIOD_RE.fullmatch(source_period) is None:
            processed.append({"source_period": source_period or None, "status": "skipped_unsupported_period"})
            continue
        if source_period in existing_periods:
            existing += 1
            processed.append({"source_period": source_period, "status": "existing"})
            continue

        report_document_id = int(item.get("report_document_id") or 0)
        if report_document_id <= 0:
            errors.append({"source_period": source_period, "error": "missing_report_document_id"})
            continue
        document = await repository.first(
            "SELECT external_id, url FROM source_documents WHERE id=? LIMIT 1",
            (report_document_id,),
        )
        if document is None:
            errors.append({"source_period": source_period, "error": "missing_report_source_document"})
            continue
        external_id = str(document.get("external_id") or "")
        match = _NEWSWEB_REPORT_RE.fullmatch(external_id)
        if match is None:
            errors.append({"source_period": source_period, "error": "invalid_report_external_id"})
            continue
        message_id, attachment_id = (int(value) for value in match.groups())

        try:
            text = await loader(message_id, attachment_id)
            parsed = parse_report_interest_income(text, source_period)
        except Exception as exc:
            errors.append({"source_period": source_period, "message_id": message_id, "error": str(exc)[:600]})
            continue
        if not parsed.get("valid"):
            errors.append(
                {
                    "source_period": source_period,
                    "message_id": message_id,
                    "error": "interest_parser_validation_failed:" + ",".join(parsed.get("issues") or []),
                }
            )
            continue

        anchor = parsed["facts"]
        metadata = {
            "input_kind": "INTEREST_INCOME_ANCHOR",
            **anchor,
            "source_locator": (
                f"Auto-extracted from NewsWeb report document {report_document_id}: "
                "consolidated cash-flow row 'Interest income received' and report USD/NOK period table."
            ),
            "source_document_id": report_document_id,
            "interest_parser_version": INTEREST_PARSER_VERSION,
            "auto_extracted": True,
            "curated": False,
            "attribution_policy": ATTRIBUTION_POLICY,
            "notes": (
                "Exact reported half-year cash interest. Arbitrary NAV-history windows allocate the USD amount "
                "evenly by calendar day and translate it using Otello's reported USD/NOK period rates."
            ),
        }
        await repository.create_source_document(
            source_code="NEWSWEB",
            external_id=f"economic-nav-interest:{source_period}",
            document_type="ECONOMIC_NAV_INTEREST_INCOME_ANCHOR",
            title=f"Economic NAV interest-income anchor {source_period}",
            url=str(document.get("url") or f"internal://otello-report/{report_document_id}"),
            published_at=f"{anchor['source_period_end']}T00:00:00Z",
            metadata=metadata,
        )
        existing_periods.add(source_period)
        written += 1
        processed.append(
            {
                "source_period": source_period,
                "status": "inserted",
                "amount_usd": anchor["amount_usd"],
                "message_id": message_id,
            }
        )

    status = "ok" if not errors else ("partial" if written or existing else "error")
    return {
        "status": status,
        "candidates": sum(1 for item in results if isinstance(item, dict) and item.get("status") == "applied"),
        "written": written,
        "existing": existing,
        "errors": errors,
        "results": processed,
        "parser_version": INTEREST_PARSER_VERSION,
    }
