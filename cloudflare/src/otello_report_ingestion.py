from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

from pypdf import PdfReader

try:
    from .newsweb_client import attachment_url, fetch_attachment, fetch_message
    from .r2_archive import archive_bytes, archive_json
except ImportError:
    from newsweb_client import attachment_url, fetch_attachment, fetch_message
    from r2_archive import archive_bytes, archive_json

REPORT_PARSER_VERSION = "otello-financial-report-v4"
AUTO_REPORT_START_DATE = "2026-08-19"
MAX_REPORT_CANDIDATES = 8
MAX_NAV_BACKFILL_DATES = 90
MAX_FX_LOOKBACK_DAYS = 7
OPTION_GRANT_DATE = date(2025, 9, 15)

_SPACE_RE = re.compile(r"\s+")
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/20\d{2})\b")
_NUMBER_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?|(?<!\w)-(?!\w)")
_POST_REPORT_PATENT_CASH_RE = re.compile(
    r"\bOn\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s+(20\d{2}),\s+Otello\s+received\s+the\s+final\s+install?ment\s+from\s+the\s+sale\s+"
    r"of\s+patents\s+from\s+(20\d{2}),\s+being\s+a\s+net\s+amount\s+of\s+USD\s+"
    r"([\d,]+(?:\.\d+)?)\s+thousand\b",
    re.I,
)


def _decimal_text(value: Decimal | str | int | float) -> str:
    return format(Decimal(str(value)), "f")


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_number(token: str) -> Decimal:
    value = token.strip().replace(",", "")
    if value == "-":
        return Decimal("0")
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Ugyldig rapporttall: {token!r}") from exc
    return -number if negative else number


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\u00a0", " ").splitlines():
        line = _SPACE_RE.sub(" ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _line_index(lines: list[str], pattern: str) -> int | None:
    regex = re.compile(pattern, re.I)
    for index, line in enumerate(lines):
        if regex.search(line):
            return index
    return None


def _row_current_value(
    lines: list[str],
    patterns: tuple[str, ...],
    *,
    start: int = 0,
    end: int | None = None,
    skip_leading_note_reference: bool = False,
) -> Decimal | None:
    """Return the current-period value, ignoring an explicit leading Note column when requested."""
    limit = len(lines) if end is None else min(end, len(lines))
    regexes = [re.compile(pattern, re.I) for pattern in patterns]
    for index in range(start, limit):
        line = lines[index]
        if not any(regex.search(line) for regex in regexes):
            continue
        tokens = _NUMBER_RE.findall(line)
        if tokens:
            if (
                skip_leading_note_reference
                and len(tokens) >= 2
                and re.fullmatch(r"\d{1,2}", tokens[0])
            ):
                tokens = tokens[1:]
            return _parse_number(tokens[0])
        if index + 1 < limit:
            next_tokens = _NUMBER_RE.findall(lines[index + 1])
            if next_tokens:
                return _parse_number(next_tokens[0])
    return None


def _report_date(lines: list[str]) -> date | None:
    section = _line_index(lines, r"consolidated statement of financial position")
    if section is None:
        return None
    for line in lines[section : min(section + 35, len(lines))]:
        dates = _DATE_RE.findall(line)
        if not dates:
            continue
        month, day, year = (int(part) for part in dates[0].split("/"))
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _report_kind(text_upper: str, report_day: date) -> str:
    if "FIRST-HALF REPORT" in text_upper or "FIRST HALF REPORT" in text_upper:
        return "1H"
    if "SECOND-HALF REPORT" in text_upper or "SECOND HALF REPORT" in text_upper:
        return "2H"
    if "ANNUAL REPORT" in text_upper:
        return "FY"
    if report_day.month == 6:
        return "1H"
    if report_day.month == 12:
        return "2H"
    return "UNKNOWN"


def _period_days(kind: str, report_day: date) -> int:
    if kind == "1H":
        start = date(report_day.year, 1, 1)
    elif kind == "2H":
        start = date(report_day.year, 7, 1)
    else:
        start = date(report_day.year, 1, 1)
    return (report_day - start).days + 1


def _period_code(kind: str, report_day: date) -> str:
    year = str(report_day.year)[-2:]
    return f"{kind}{year}" if kind in {"1H", "2H", "FY"} else report_day.isoformat()


def _thousands_to_usd(value: Decimal | None) -> Decimal | None:
    return None if value is None else value * Decimal("1000")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _facts_for_json(facts: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in facts.items()}


def _post_report_patent_cash_events(lines: list[str], report_day: date) -> tuple[list[dict[str, Any]], list[str]]:
    normalized = " ".join(lines)
    events: list[dict[str, Any]] = []
    issues: list[str] = []
    for match in _POST_REPORT_PATENT_CASH_RE.finditer(normalized):
        month, day, year, patent_year, amount_k = match.groups()
        event_day = datetime.strptime(f"{month} {day}, {year}", "%B %d, %Y").date()
        if event_day <= report_day:
            issues.append("post_report_cash_event_not_after_report_date")
            continue
        amount_usd = Decimal(amount_k.replace(",", "")) * Decimal("1000")
        if amount_usd <= 0:
            issues.append("post_report_cash_event_nonpositive")
            continue
        events.append(
            {
                "event_type": "PATENT_SALE_FINAL_INSTALMENT",
                "movement_date": event_day,
                "amount_usd": amount_usd,
                "description": f"Final net instalment from the {patent_year} patent sale",
            }
        )
    return events, issues


def parse_otello_financial_report(text: str) -> dict[str, Any]:
    """Parse source-backed Otello report anchors and fail closed on structural drift."""
    lines = _clean_lines(text)
    upper = "\n".join(lines).upper()
    issues: list[str] = []

    if "OTELLO CORPORATION ASA" not in upper:
        issues.append("missing_otello_issuer_signature")
    if "CONSOLIDATED STATEMENT OF FINANCIAL POSITION" not in upper:
        issues.append("missing_financial_position")
    if not re.search(
        r"USD\s*(?:\(\s*)?(?:IN\s+)?THOUSANDS|US\$\s*(?:\(\s*)?(?:IN\s+)?THOUSANDS",
        upper,
    ):
        issues.append("missing_usd_thousands_unit")

    report_day = _report_date(lines)
    if report_day is None:
        issues.append("missing_report_date")
        return {
            "valid": False,
            "parser_version": REPORT_PARSER_VERSION,
            "issues": issues,
            "facts": {},
        }

    kind = _report_kind(upper, report_day)
    if kind == "UNKNOWN":
        issues.append("unknown_report_period")

    post_report_cash_events, post_report_issues = _post_report_patent_cash_events(lines, report_day)
    issues.extend(post_report_issues)

    balance_start = _line_index(lines, r"consolidated statement of financial position") or 0
    balance_end = _line_index(lines[balance_start + 1 :], r"consolidated statement of cash flows")
    if balance_end is None:
        balance_end = min(balance_start + 180, len(lines))
    else:
        balance_end = balance_start + 1 + balance_end

    cash_k = _row_current_value(
        lines,
        (r"^cash and cash equivalents\b",),
        start=balance_start,
        end=balance_end,
    )
    total_assets_k = _row_current_value(
        lines,
        (r"^total assets\s+(?:\(?-?\d|-)",),
        start=balance_start,
        end=balance_end,
    )
    total_equity_k = _row_current_value(
        lines,
        (r"^total equity\s+(?:\(?-?\d|-)",),
        start=balance_start,
        end=balance_end,
    )
    total_liabilities_k = _row_current_value(
        lines,
        (r"^total liabilities\s+(?:\(?-?\d|-)",),
        start=balance_start,
        end=balance_end,
    )
    option_liability_k = _row_current_value(
        lines,
        (
            r"^options? liabilit(?:y|ies)\b",
            r"^share[- ]based payment liabilit(?:y|ies)\b",
            r"^share[- ]based compensation liabilit(?:y|ies)\b",
        ),
        start=balance_start,
        end=balance_end,
        skip_leading_note_reference=True,
    )

    bemobi_k = _row_current_value(
        lines,
        (
            r"^investments? in bemobi mobile tech(?:nology)?\b",
            r"^bemobi mobile tech(?:nology)?\b.*(?:associate|carrying)",
            r"carrying (?:amount|value).*bemobi",
        ),
    )
    other_shares_k = _row_current_value(
        lines,
        (
            r"^investments? in other shares\b",
            r"^other shares\b",
        ),
    )

    pnl_start = _line_index(lines, r"consolidated statement of (?:profit or loss|income)")
    if pnl_start is None:
        pnl_start = _line_index(lines, r"consolidated statement of comprehensive income")
    pnl_start = pnl_start or 0
    pnl_end = min(pnl_start + 140, len(lines))
    employee_k = _row_current_value(
        lines,
        (r"^employee benefits expense\b", r"^employee benefit expense\b"),
        start=pnl_start,
        end=pnl_end,
        skip_leading_note_reference=True,
    )
    other_opex_k = _row_current_value(
        lines,
        (r"^other operating expenses?\b",),
        start=pnl_start,
        end=pnl_end,
    )
    stock_comp_k = _row_current_value(
        lines,
        (
            r"^stock[- ]based compensation expenses?\b",
            r"^share[- ]based compensation expenses?\b",
        ),
    )

    required = {
        "cash": cash_k,
        "total_assets": total_assets_k,
        "total_equity": total_equity_k,
        "total_liabilities": total_liabilities_k,
        "bemobi_carrying": bemobi_k,
        "other_shares_investment": other_shares_k,
        "employee_benefits": employee_k,
        "other_operating_expenses": other_opex_k,
    }
    for name, value in required.items():
        if value is None:
            issues.append(f"missing_{name}")

    if report_day >= OPTION_GRANT_DATE and option_liability_k is None:
        issues.append("missing_option_liability_post_grant")
    if report_day < OPTION_GRANT_DATE and option_liability_k is None:
        option_liability_k = Decimal("0")
    if report_day >= OPTION_GRANT_DATE and stock_comp_k is None:
        issues.append("missing_stock_compensation_post_grant")
    if report_day < OPTION_GRANT_DATE and stock_comp_k is None:
        stock_comp_k = Decimal("0")

    if total_assets_k is not None and total_equity_k is not None and total_liabilities_k is not None:
        balance_gap_k = total_assets_k - total_equity_k - total_liabilities_k
        if abs(balance_gap_k) > Decimal("10"):
            issues.append(f"balance_sheet_not_balanced:{_decimal_text(balance_gap_k)}k")
    else:
        balance_gap_k = None

    numeric_nonnegative = {
        "cash": cash_k,
        "total_assets": total_assets_k,
        "bemobi_carrying": bemobi_k,
        "other_shares_investment": other_shares_k,
        "total_liabilities": total_liabilities_k,
        "option_liability": option_liability_k,
    }
    for name, value in numeric_nonnegative.items():
        if value is not None and value < 0:
            issues.append(f"negative_{name}")

    if cash_k is not None and cash_k > Decimal("1000000"):
        issues.append("cash_out_of_range")
    if bemobi_k is not None and bemobi_k > Decimal("1000000"):
        issues.append("bemobi_carrying_out_of_range")
    if other_shares_k is not None and other_shares_k > Decimal("1000000"):
        issues.append("other_shares_investment_out_of_range")

    cash_usd = _thousands_to_usd(cash_k)
    total_assets_usd = _thousands_to_usd(total_assets_k)
    total_equity_usd = _thousands_to_usd(total_equity_k)
    total_liabilities_usd = _thousands_to_usd(total_liabilities_k)
    bemobi_usd = _thousands_to_usd(bemobi_k)
    other_shares_usd = _thousands_to_usd(other_shares_k)
    option_liability_usd = _thousands_to_usd(option_liability_k)

    ona_usd = None
    if None not in (total_assets_usd, cash_usd, bemobi_usd, total_liabilities_usd):
        ona_usd = total_assets_usd - cash_usd - bemobi_usd - total_liabilities_usd
        if abs(ona_usd) > Decimal("100000000"):
            issues.append("derived_ona_out_of_range")

    recurring_opex_usd = None
    if None not in (employee_k, other_opex_k, stock_comp_k):
        employee_abs = abs(employee_k)
        other_abs = abs(other_opex_k)
        stock_abs = abs(stock_comp_k)
        if stock_abs > employee_abs + Decimal("10"):
            issues.append("stock_comp_exceeds_employee_benefits")
        else:
            recurring_opex_usd = (employee_abs - stock_abs + other_abs) * Decimal("1000")

    facts = {
        "report_date": report_day,
        "report_kind": kind,
        "source_period": _period_code(kind, report_day),
        "period_days": _period_days(kind, report_day),
        "cash_usd": cash_usd,
        "total_assets_usd": total_assets_usd,
        "total_equity_usd": total_equity_usd,
        "total_liabilities_usd": total_liabilities_usd,
        "bemobi_carrying_usd": bemobi_usd,
        "other_shares_investment_usd": other_shares_usd,
        "option_liability_usd": option_liability_usd,
        "other_net_assets_usd": ona_usd,
        "employee_benefits_usd": _thousands_to_usd(abs(employee_k)) if employee_k is not None else None,
        "other_operating_expenses_usd": _thousands_to_usd(abs(other_opex_k)) if other_opex_k is not None else None,
        "stock_compensation_usd": _thousands_to_usd(abs(stock_comp_k)) if stock_comp_k is not None else None,
        "recurring_opex_usd": recurring_opex_usd,
        "balance_gap_usd": _thousands_to_usd(balance_gap_k),
        "post_report_cash_events": post_report_cash_events,
    }
    return {
        "valid": not issues,
        "parser_version": REPORT_PARSER_VERSION,
        "issues": issues,
        "facts": facts,
    }


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


async def _nearest_usd_nok(repository, report_date: str) -> dict[str, Any] | None:
    floor = (date.fromisoformat(report_date) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT id, substr(observed_at,1,10) AS rate_date, rate, source_document_id
        FROM fx_rates
        WHERE base_currency='USD' AND quote_currency='NOK'
          AND substr(observed_at,1,10) <= ? AND substr(observed_at,1,10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (report_date, floor),
    )


async def _latest_reported_cash_date(repository) -> str | None:
    row = await repository.first(
        "SELECT MAX(as_of_date) AS d FROM cash_anchors WHERE anchor_type='REPORTED'"
    )
    return str(row["d"]) if row and row.get("d") else None


async def _active_bemobi_receivable_count(repository, report_date: str) -> int:
    row = await repository.first(
        """
        SELECT COUNT(*) AS n
        FROM corporate_actions ca
        JOIN instruments i ON i.id=ca.issuer_instrument_id
        WHERE i.symbol='BMOB3' AND ca.action_type IN ('DIVIDEND','JCP')
          AND ca.ex_date IS NOT NULL AND ca.payment_date IS NOT NULL
          AND ca.ex_date <= ? AND ca.payment_date > ?
        """,
        (report_date, report_date),
    )
    return int(row["n"] or 0) if row else 0


async def _pending_report_news(repository, target_date: str) -> list[dict[str, Any]]:
    return await repository.all(
        """
        SELECT cn.id AS company_news_id, cn.headline, cn.published_at,
               cn.processing_status, cn.source_document_id,
               sd.external_id, sd.metadata_json, sd.url
        FROM company_news cn
        JOIN source_documents sd ON sd.id=cn.source_document_id
        WHERE cn.category='RESULTS' AND cn.processing_status='PARSED'
          AND substr(COALESCE(cn.published_at,''),1,10) >= ?
          AND substr(COALESCE(cn.published_at,''),1,10) <= ?
        ORDER BY cn.published_at, cn.id
        LIMIT ?
        """,
        (AUTO_REPORT_START_DATE, target_date, MAX_REPORT_CANDIDATES),
    )


def _message_id(candidate: dict[str, Any]) -> int | None:
    try:
        metadata = json.loads(str(candidate.get("metadata_json") or "{}"))
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    raw = metadata.get("newsweb_message_id")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    match = re.search(r"newsweb-message:(\d+)", str(candidate.get("external_id") or ""))
    return int(match.group(1)) if match else None


async def _set_news_status(
    repository,
    company_news_id: int,
    *,
    status: str,
    summary: str | None,
    notes: str,
) -> None:
    await repository.run(
        """
        UPDATE company_news
        SET processing_status=?, summary=?, notes=?,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=?
        """,
        (status, summary, notes[:4000], company_news_id),
    )


async def _archive_and_stage_report(
    repository,
    bucket,
    *,
    message,
    attachment,
    pdf_bytes: bytes,
    parsed: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    facts_json = _facts_for_json(parsed["facts"])
    logical_date = str(facts_json["report_date"])
    filename = attachment.name.strip() or f"otello-report-{message.message_id}-{attachment.attachment_id}.pdf"
    pdf_archive = await archive_bytes(
        bucket,
        pdf_bytes,
        source="newsweb",
        kind="otello-financial-report",
        logical_date=logical_date,
        filename=filename,
    )
    parsed_payload = {
        "parser_version": REPORT_PARSER_VERSION,
        "message_id": message.message_id,
        "attachment_id": attachment.attachment_id,
        "attachment_name": attachment.name,
        "published_at": message.published_at,
        "title": message.title,
        "validation": {"valid": parsed["valid"], "issues": parsed["issues"]},
        "facts": facts_json,
        "pdf": pdf_archive,
    }
    parsed_archive = await archive_json(
        bucket,
        parsed_payload,
        source="newsweb",
        kind="otello-financial-report-parsed",
        logical_date=logical_date,
        filename=f"otello-report-{message.message_id}-{attachment.attachment_id}.json",
    )
    metadata = {
        **parsed_payload,
        "parsed_r2": parsed_archive,
        "source_quality": "OFFICIAL_ORIGINAL",
        "auto_apply_policy": "STRICT_VALIDATION_FAIL_CLOSED",
        "auto_apply_status": "STAGED",
    }
    document_id = await repository.create_source_document(
        source_code="NEWSWEB",
        external_id=f"newsweb-report:{message.message_id}:{attachment.attachment_id}",
        document_type="OTELLO_FINANCIAL_REPORT",
        title=message.title,
        url=attachment_url(message.message_id, attachment.attachment_id),
        published_at=message.published_at,
        content_sha256=pdf_archive["content_sha256"],
        metadata=metadata,
    )
    return document_id, {"pdf": pdf_archive, "parsed": parsed_archive}


async def _set_report_document_apply_status(repository, report_doc_id: int, status: str) -> None:
    row = await repository.first(
        "SELECT metadata_json FROM source_documents WHERE id=? LIMIT 1",
        (report_doc_id,),
    )
    if row is None:
        raise RuntimeError("Rapportens source_document mangler")
    try:
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    metadata["auto_apply_status"] = status
    await repository.run(
        """
        UPDATE source_documents
        SET metadata_json=?, fetched_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=?
        """,
        (json.dumps(metadata, ensure_ascii=False, sort_keys=True), report_doc_id),
    )


async def _cleanup_report_anchors(repository, report_doc_id: int) -> None:
    await repository.run(
        "DELETE FROM cash_movements WHERE source_document_id=? AND external_movement_id LIKE 'otello-report-post-cash:%'",
        (report_doc_id,),
    )
    await repository.run(
        """
        DELETE FROM other_net_assets_anchors
        WHERE reported_anchor_id IN (
            SELECT id FROM other_net_assets_reported_anchors WHERE source_document_id=?
        )
        """,
        (report_doc_id,),
    )
    await repository.run(
        "DELETE FROM other_net_assets_reported_anchors WHERE source_document_id=?",
        (report_doc_id,),
    )
    await repository.run(
        "DELETE FROM cash_anchors WHERE source_document_id=?",
        (report_doc_id,),
    )
    await _set_report_document_apply_status(repository, report_doc_id, "STAGED")


async def _upsert_cash_anchor(repository, report_doc_id: int, facts: dict[str, Any], fx: dict[str, Any]) -> int:
    report_date = str(facts["report_date"])
    cash_usd = Decimal(str(facts["cash_usd"]))
    usd_nok = Decimal(str(fx["rate"]))
    amount_nok = cash_usd * usd_nok
    await repository.run(
        """
        INSERT INTO cash_anchors(
            as_of_date, amount_nok, reported_amount, reported_currency,
            fx_rate_to_nok, anchor_type, source_document_id, notes
        ) VALUES (?, ?, ?, 'USD', ?, 'REPORTED', ?, ?)
        ON CONFLICT(as_of_date, anchor_type, source_document_id) DO UPDATE SET
            amount_nok=excluded.amount_nok,
            reported_amount=excluded.reported_amount,
            reported_currency=excluded.reported_currency,
            fx_rate_to_nok=excluded.fx_rate_to_nok,
            notes=excluded.notes
        """,
        (
            report_date,
            _decimal_text(amount_nok),
            _decimal_text(cash_usd),
            _decimal_text(usd_nok),
            report_doc_id,
            f"Auto-extracted by {REPORT_PARSER_VERSION}; USD/NOK {fx['rate']} from {fx['rate_date']}.",
        ),
    )
    row = await repository.first(
        """
        SELECT id FROM cash_anchors
        WHERE as_of_date=? AND anchor_type='REPORTED' AND source_document_id=?
        LIMIT 1
        """,
        (report_date, report_doc_id),
    )
    if row is None:
        raise RuntimeError("Rapportens cash-anchor ble skrevet, men kunne ikke leses tilbake")
    return int(row["id"])


async def _prepare_post_report_cash_events(repository, facts: dict[str, Any]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for raw_event in facts.get("post_report_cash_events") or []:
        event = dict(raw_event)
        movement_date = str(event["movement_date"])
        amount_usd = Decimal(str(event["amount_usd"]))
        fx = await _nearest_usd_nok(repository, movement_date)
        if fx is None:
            raise ValueError(f"Mangler USD/NOK for bekreftet kontantbevegelse {movement_date}")
        usd_nok = Decimal(str(fx["rate"]))
        prepared.append(
            {
                **event,
                "movement_date": movement_date,
                "amount_usd": amount_usd,
                "fx": fx,
                "amount_nok": amount_usd * usd_nok,
            }
        )
    return prepared


async def _upsert_post_report_cash_events(
    repository,
    report_doc_id: int,
    prepared_events: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for event in prepared_events:
        movement_date = str(event["movement_date"])
        event_type = str(event["event_type"])
        amount_usd = Decimal(str(event["amount_usd"]))
        amount_nok = Decimal(str(event["amount_nok"]))
        fx = event["fx"]
        external_id = f"otello-report-post-cash:{event_type}:{movement_date}"
        existing = await repository.first(
            """
            SELECT id, amount_original, currency, amount_nok
            FROM cash_movements WHERE external_movement_id=? LIMIT 1
            """,
            (external_id,),
        )
        if existing is not None:
            if (
                str(existing.get("currency") or "") != "USD"
                or Decimal(str(existing.get("amount_original") or "0")) != amount_usd
            ):
                raise ValueError(f"Konflikt i eksisterende kontantbevegelse {external_id}")
            results.append(
                {
                    "status": "existing",
                    "id": int(existing["id"]),
                    "external_movement_id": external_id,
                    "movement_date": movement_date,
                }
            )
            continue
        await repository.run(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, amount_original, currency,
                fx_rate_to_nok, description, source_document_id, confidence, external_movement_id
            ) VALUES (?, 'OTHER', ?, ?, 'USD', ?, ?, ?, 'CONFIRMED', ?)
            """,
            (
                movement_date,
                _decimal_text(amount_nok),
                _decimal_text(amount_usd),
                _decimal_text(Decimal(str(fx["rate"]))),
                str(event["description"]),
                report_doc_id,
                external_id,
            ),
        )
        row = await repository.first(
            "SELECT id FROM cash_movements WHERE external_movement_id=? LIMIT 1",
            (external_id,),
        )
        if row is None:
            raise RuntimeError("Rapportens kontantbevegelse ble skrevet, men kunne ikke leses tilbake")
        results.append(
            {
                "status": "inserted",
                "id": int(row["id"]),
                "external_movement_id": external_id,
                "movement_date": movement_date,
                "amount_usd": _decimal_text(amount_usd),
                "amount_nok": _decimal_text(amount_nok),
                "fx_rate": str(fx["rate"]),
                "fx_date": str(fx["rate_date"]),
            }
        )
    return {"status": "ok", "count": len(results), "events": results}


async def _upsert_ona_anchor(repository, report_doc_id: int, facts: dict[str, Any], fx: dict[str, Any]) -> tuple[int, int]:
    report_date = str(facts["report_date"])
    total_assets = Decimal(str(facts["total_assets_usd"]))
    cash = Decimal(str(facts["cash_usd"]))
    bemobi = Decimal(str(facts["bemobi_carrying_usd"]))
    other_shares = Decimal(str(facts["other_shares_investment_usd"]))
    liabilities = Decimal(str(facts["total_liabilities_usd"]))
    option = Decimal(str(facts.get("option_liability_usd") or "0"))
    ona = total_assets - cash - bemobi - liabilities
    associated_receivable = Decimal("0")
    base = ona - associated_receivable
    base_ex_option = base + option

    await repository.run(
        """
        INSERT INTO other_net_assets_reported_anchors(
            as_of_date, total_assets_reported, cash_reported, bemobi_carrying_reported,
            total_liabilities_reported, reported_currency, other_net_assets_reported,
            precision_status, restated, source_document_id, source_locator, notes,
            associated_receivable_reported, base_other_net_assets_reported,
            option_liability_reported, base_other_net_assets_ex_option_reported,
            other_shares_investment_reported
        ) VALUES (?, ?, ?, ?, ?, 'USD', ?, 'ROUNDED_1K', 0, ?, ?, ?, '0', ?, ?, ?, ?)
        ON CONFLICT(as_of_date, source_document_id) DO UPDATE SET
            total_assets_reported=excluded.total_assets_reported,
            cash_reported=excluded.cash_reported,
            bemobi_carrying_reported=excluded.bemobi_carrying_reported,
            total_liabilities_reported=excluded.total_liabilities_reported,
            other_net_assets_reported=excluded.other_net_assets_reported,
            precision_status=excluded.precision_status,
            source_locator=excluded.source_locator,
            notes=excluded.notes,
            associated_receivable_reported=excluded.associated_receivable_reported,
            base_other_net_assets_reported=excluded.base_other_net_assets_reported,
            option_liability_reported=excluded.option_liability_reported,
            base_other_net_assets_ex_option_reported=excluded.base_other_net_assets_ex_option_reported,
            other_shares_investment_reported=excluded.other_shares_investment_reported
        """,
        (
            report_date,
            _decimal_text(total_assets),
            _decimal_text(cash),
            _decimal_text(bemobi),
            _decimal_text(liabilities),
            _decimal_text(ona),
            report_doc_id,
            "Consolidated statement of financial position; Bemobi and other-shares investment note",
            f"Auto-extracted by {REPORT_PARSER_VERSION}; associated Bemobi receivable verified as none at report date.",
            _decimal_text(base),
            _decimal_text(option),
            _decimal_text(base_ex_option),
            _decimal_text(other_shares),
        ),
    )
    reported = await repository.first(
        """
        SELECT id FROM other_net_assets_reported_anchors
        WHERE as_of_date=? AND source_document_id=? LIMIT 1
        """,
        (report_date, report_doc_id),
    )
    if reported is None:
        raise RuntimeError("Rapportens ONA-anchor ble skrevet, men kunne ikke leses tilbake")
    reported_id = int(reported["id"])

    usd_nok = Decimal(str(fx["rate"]))
    amount_nok = ona * usd_nok
    hash_payload = {
        "reported_anchor_id": reported_id,
        "amount_usd": _decimal_text(ona),
        "associated_receivable_usd": "0",
        "base_other_net_assets_usd": _decimal_text(base),
        "option_liability_usd": _decimal_text(option),
        "base_ex_option_usd": _decimal_text(base_ex_option),
        "other_shares_investment_usd": _decimal_text(other_shares),
        "usd_nok_rate": _decimal_text(usd_nok),
        "fx_rate_id": fx["id"],
        "fx_rate_date": fx["rate_date"],
        "restated": False,
    }
    existing = await repository.first(
        "SELECT id FROM other_net_assets_anchors WHERE reported_anchor_id=? LIMIT 1",
        (reported_id,),
    )
    description = (
        "Reported ONA excluding cash and Bemobi carrying value; option liability decomposed for daily valuation"
    )
    notes = (
        f"Auto-extracted by {REPORT_PARSER_VERSION}; USD/NOK {_decimal_text(usd_nok)} from {fx['rate_date']}; "
        f"option liability USD {_decimal_text(option)}; base ex option USD {_decimal_text(base_ex_option)}; "
        f"other shares USD {_decimal_text(other_shares)}."
    )
    values = (
        report_date,
        _decimal_text(amount_nok),
        description,
        report_doc_id,
        notes,
        reported_id,
        _decimal_text(ona),
        _decimal_text(usd_nok),
        "REPORTED",
        _json_hash(hash_payload),
    )
    if existing is None:
        await repository.run(
            """
            INSERT INTO other_net_assets_anchors(
                as_of_date, amount_nok, description, source_document_id, notes,
                reported_anchor_id, amount_usd, fx_rate_to_nok, quality, inputs_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
    else:
        await repository.run(
            """
            UPDATE other_net_assets_anchors
            SET as_of_date=?, amount_nok=?, description=?, source_document_id=?, notes=?,
                reported_anchor_id=?, amount_usd=?, fx_rate_to_nok=?, quality=?, inputs_hash=?
            WHERE id=?
            """,
            (*values, int(existing["id"])),
        )
    converted = await repository.first(
        "SELECT id FROM other_net_assets_anchors WHERE reported_anchor_id=? LIMIT 1",
        (reported_id,),
    )
    if converted is None:
        raise RuntimeError("Rapportens konverterte ONA-anchor kunne ikke leses tilbake")
    return reported_id, int(converted["id"])


async def _upsert_cost_anchors(repository, report_doc_id: int, facts: dict[str, Any]) -> dict[str, Any]:
    recurring = facts.get("recurring_opex_usd")
    if recurring is None:
        return {"status": "skipped", "reason": "missing_recurring_opex"}
    report_date = str(facts["report_date"])
    source_period = str(facts["source_period"])
    period_days = int(facts["period_days"])
    base_meta = {
        "scenario": "BASE",
        "effective_from": report_date,
        "amount_usd": _decimal_text(Decimal(str(recurring))),
        "period_days": period_days,
        "source_period": source_period,
        "source_measure": "EMPLOYEE_BENEFITS_EX_STOCK_COMP_PLUS_OTHER_OPEX",
        "source_document_id": report_doc_id,
        "parser_version": REPORT_PARSER_VERSION,
    }
    await repository.create_source_document(
        source_code="NEWSWEB",
        external_id=f"otello-report-cost-base:{report_date}",
        document_type="ECONOMIC_NAV_COST_ANCHOR",
        title=f"Otello recurring operating cost anchor {source_period}",
        url=f"internal://otello-report/{report_doc_id}/cost/base",
        published_at=report_date,
        content_sha256=_json_hash(base_meta),
        metadata=base_meta,
    )

    rows = await repository.all(
        """
        SELECT id, metadata_json FROM source_documents
        WHERE document_type='ECONOMIC_NAV_COST_ANCHOR'
        ORDER BY id DESC LIMIT 30
        """
    )
    previous: dict[str, Any] | None = None
    for row in rows:
        try:
            meta = json.loads(str(row.get("metadata_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if meta.get("scenario") != "BASE":
            continue
        effective = str(meta.get("effective_from") or "")
        if effective and effective < report_date:
            previous = meta
            break

    conservative_written = False
    if previous is not None:
        try:
            previous_days = int(previous["period_days"])
            previous_amount = Decimal(str(previous["amount_usd"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            previous_days = 0
            previous_amount = Decimal("0")
        if 120 <= previous_days < 250 and previous_amount >= 0:
            conservative_meta = {
                "scenario": "CONSERVATIVE",
                "effective_from": report_date,
                "amount_usd": _decimal_text(previous_amount + Decimal(str(recurring))),
                "period_days": previous_days + period_days,
                "source_period": f"TTM_TO_{source_period}",
                "source_measure": "TRAILING_TWO_HALF_YEAR_RECURRING_OPEX_EX_STOCK_COMP",
                "source_document_id": report_doc_id,
                "prior_source_document_id": previous.get("source_document_id"),
                "parser_version": REPORT_PARSER_VERSION,
            }
            await repository.create_source_document(
                source_code="NEWSWEB",
                external_id=f"otello-report-cost-conservative:{report_date}",
                document_type="ECONOMIC_NAV_COST_ANCHOR",
                title=f"Otello conservative operating cost anchor through {source_period}",
                url=f"internal://otello-report/{report_doc_id}/cost/conservative",
                published_at=report_date,
                content_sha256=_json_hash(conservative_meta),
                metadata=conservative_meta,
            )
            conservative_written = True

    return {
        "status": "ok",
        "base_written": True,
        "conservative_written": conservative_written,
        "source_period": source_period,
        "recurring_opex_usd": _decimal_text(Decimal(str(recurring))),
    }


async def _backfill_affected_nav(repository, report_date: str, target_date: str) -> dict[str, Any]:
    try:
        from .nav_refresh import (
            refresh_core_nav_if_dirty,
            refresh_daily_cash_if_dirty,
            refresh_full_nav_if_dirty,
            refresh_other_net_assets_if_dirty,
        )
    except ImportError:
        from nav_refresh import (
            refresh_core_nav_if_dirty,
            refresh_daily_cash_if_dirty,
            refresh_full_nav_if_dirty,
            refresh_other_net_assets_if_dirty,
        )

    rows = await repository.all(
        """
        SELECT DISTINCT substr(as_of_at,1,10) AS d
        FROM nav_snapshots
        WHERE nav_scope='CORE' AND substr(as_of_at,1,10) >= ? AND substr(as_of_at,1,10) <= ?
        ORDER BY d
        LIMIT ?
        """,
        (report_date, target_date, MAX_NAV_BACKFILL_DATES),
    )
    dates = [str(row["d"]) for row in rows if row.get("d")]
    rebuilt = 0
    not_ready: list[dict[str, Any]] = []
    for day in dates:
        steps = {
            "cash": await refresh_daily_cash_if_dirty(repository, day),
            "ona": await refresh_other_net_assets_if_dirty(repository, day),
        }
        steps["core"] = await refresh_core_nav_if_dirty(repository, day)
        steps["full"] = await refresh_full_nav_if_dirty(repository, day)
        if all(result.get("status") == "ok" for result in steps.values()):
            rebuilt += 1
        else:
            not_ready.append({"date": day, "steps": steps})
    return {
        "status": "ok" if not not_ready else "partial",
        "from": report_date,
        "to": target_date,
        "dates_considered": len(dates),
        "dates_rebuilt": rebuilt,
        "not_ready": not_ready[:10],
    }


async def _apply_report(
    repository,
    *,
    report_doc_id: int,
    facts: dict[str, Any],
    target_date: str,
) -> dict[str, Any]:
    report_date = str(facts["report_date"])
    fx = await _nearest_usd_nok(repository, report_date)
    if fx is None:
        raise ValueError(f"Mangler USD/NOK for rapportdato {report_date}")

    active_receivables = await _active_bemobi_receivable_count(repository, report_date)
    if active_receivables:
        raise ValueError(
            "Bemobi-utdeling er opptjent men ikke betalt på rapportdato; "
            "rapportens tilknyttede fordring må identifiseres eksplisitt før automatisk ONA-anker"
        )

    prepared_cash_events = await _prepare_post_report_cash_events(repository, facts)

    try:
        cash_id = await _upsert_cash_anchor(repository, report_doc_id, facts, fx)
        ona_reported_id, ona_converted_id = await _upsert_ona_anchor(repository, report_doc_id, facts, fx)
        post_report_cash = await _upsert_post_report_cash_events(
            repository,
            report_doc_id,
            prepared_cash_events,
        )
    except Exception:
        await _cleanup_report_anchors(repository, report_doc_id)
        raise

    await _set_report_document_apply_status(repository, report_doc_id, "APPLIED")

    warnings: list[dict[str, str]] = []
    try:
        cost_result = await _upsert_cost_anchors(repository, report_doc_id, facts)
    except Exception as exc:
        cost_result = {"status": "error", "error": str(exc)[:800]}
        warnings.append({"step": "cost_anchors", "error": str(exc)[:800]})

    try:
        backfill = await _backfill_affected_nav(repository, report_date, target_date)
        if backfill.get("status") == "partial":
            warnings.append({"step": "nav_backfill", "error": "one or more historical NAV dates were not ready"})
    except Exception as exc:
        backfill = {"status": "error", "error": str(exc)[:800]}
        warnings.append({"step": "nav_backfill", "error": str(exc)[:800]})

    return {
        "status": "applied",
        "report_date": report_date,
        "cash_anchor_id": cash_id,
        "ona_reported_anchor_id": ona_reported_id,
        "ona_anchor_id": ona_converted_id,
        "post_report_cash_events": post_report_cash,
        "cost_anchors": cost_result,
        "nav_backfill": backfill,
        "warnings": warnings,
        "share_count_policy": "NOT_APPLIED_FROM_REPORT_WITHOUT_EXTERNAL_RECONCILIATION",
        "cash_fx_allocation_policy": "NO_NEW_ALLOCATION_UNLESS_REPORT_EXPLICITLY_DOCUMENTS_CURRENCIES",
    }


async def process_pending_otello_reports(
    repository,
    archive_bucket,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Download, archive, validate and apply newly published Otello financial reports.

    The path is deliberately fail-closed: source PDF and parser diagnostics are retained,
    while current production anchors remain untouched whenever a critical extraction or
    reconciliation check fails.
    """
    candidates = await _pending_report_news(repository, target_date)
    if not candidates:
        return {"status": "ok", "candidates": 0, "processed": 0, "applied": 0, "review_required": 0}

    processed: list[dict[str, Any]] = []
    applied = 0
    review_required = 0
    ignored = 0

    for candidate in candidates:
        company_news_id = int(candidate["company_news_id"])
        message_id = _message_id(candidate)
        if message_id is None:
            review_required += 1
            await _set_news_status(
                repository,
                company_news_id,
                status="REVIEW_REQUIRED",
                summary=None,
                notes="Automatisk rapportpipeline fant ikke NewsWeb messageId.",
            )
            processed.append({"company_news_id": company_news_id, "status": "review_required", "reason": "missing_message_id"})
            continue

        try:
            message = await fetch_message(message_id, fetcher=fetcher)
        except Exception as exc:
            review_required += 1
            await _set_news_status(
                repository,
                company_news_id,
                status="REVIEW_REQUIRED",
                summary=None,
                notes=f"Kunne ikke hente NewsWeb-melding {message_id}: {exc}",
            )
            processed.append({"message_id": message_id, "status": "review_required", "reason": "message_fetch_failed"})
            continue

        attempts: list[dict[str, Any]] = []
        chosen: tuple[Any, bytes, dict[str, Any]] | None = None
        for attachment in message.attachments:
            try:
                payload = await fetch_attachment(
                    message.message_id,
                    attachment.attachment_id,
                    fetcher=fetcher,
                )
                text = extract_pdf_text(payload)
                signature = "OTELLO CORPORATION ASA" in text.upper() and "CONSOLIDATED STATEMENT" in text.upper()
                if not signature:
                    attempts.append({"attachment_id": attachment.attachment_id, "name": attachment.name, "status": "not_financial_report"})
                    continue
                parsed = parse_otello_financial_report(text)
                attempts.append(
                    {
                        "attachment_id": attachment.attachment_id,
                        "name": attachment.name,
                        "status": "valid" if parsed["valid"] else "invalid",
                        "issues": parsed["issues"],
                    }
                )
                if parsed["valid"]:
                    chosen = (attachment, payload, parsed)
                    break
            except Exception as exc:
                attempts.append(
                    {
                        "attachment_id": attachment.attachment_id,
                        "name": attachment.name,
                        "status": "error",
                        "error": str(exc)[:600],
                    }
                )

        if chosen is None:
            review_required += 1
            await _set_news_status(
                repository,
                company_news_id,
                status="REVIEW_REQUIRED",
                summary="Otello-resultatmelding funnet, men rapport-PDF kunne ikke valideres automatisk.",
                notes=f"{REPORT_PARSER_VERSION}; attachment attempts={json.dumps(attempts, ensure_ascii=False)[:3000]}",
            )
            processed.append({"message_id": message_id, "status": "review_required", "attempts": attempts})
            continue

        attachment, pdf_bytes, parsed = chosen
        report_doc_id, archive = await _archive_and_stage_report(
            repository,
            archive_bucket,
            message=message,
            attachment=attachment,
            pdf_bytes=pdf_bytes,
            parsed=parsed,
        )
        facts = parsed["facts"]
        report_date = str(facts["report_date"])
        latest_cash_date = await _latest_reported_cash_date(repository)
        if latest_cash_date is not None and report_date <= latest_cash_date:
            ignored += 1
            await _set_news_status(
                repository,
                company_news_id,
                status="IGNORED",
                summary=f"Rapport {report_date} er ikke nyere enn gjeldende rapportanker {latest_cash_date}.",
                notes=(
                    f"PDF er likevel arkivert i R2. parser={REPORT_PARSER_VERSION}; "
                    f"report_document_id={report_doc_id}; r2={archive['pdf']['r2_key']}"
                ),
            )
            processed.append({"message_id": message_id, "status": "ignored", "report_date": report_date, "report_document_id": report_doc_id})
            continue

        try:
            applied_result = await _apply_report(
                repository,
                report_doc_id=report_doc_id,
                facts=facts,
                target_date=target_date,
            )
        except Exception as exc:
            review_required += 1
            await _set_news_status(
                repository,
                company_news_id,
                status="REVIEW_REQUIRED",
                summary=f"Rapport {report_date} er lastet ned og arkivert, men ikke lagt inn i NAV.",
                notes=(
                    f"Fail-closed: {exc}; parser={REPORT_PARSER_VERSION}; "
                    f"report_document_id={report_doc_id}; r2={archive['pdf']['r2_key']}"
                ),
            )
            processed.append(
                {
                    "message_id": message_id,
                    "status": "review_required",
                    "report_date": report_date,
                    "report_document_id": report_doc_id,
                    "reason": str(exc)[:800],
                }
            )
            continue

        applied += 1
        warning_count = len(applied_result.get("warnings") or [])
        post_cash_count = int((applied_result.get("post_report_cash_events") or {}).get("count") or 0)
        await _set_news_status(
            repository,
            company_news_id,
            status="APPLIED",
            summary=(
                f"Otello {facts['source_period']} automatisk innlest: cash, ONA, opsjonsanker "
                f"og driftskostnadsgrunnlag oppdatert; {post_cash_count} bekreftet(e) etterfølgende "
                f"kontantbevegelse(r) lagt inn; NAV bygget på nytt. warnings={warning_count}"
            ),
            notes=(
                f"parser={REPORT_PARSER_VERSION}; report_document_id={report_doc_id}; "
                f"r2={archive['pdf']['r2_key']}; parsed_r2={archive['parsed']['r2_key']}; "
                "aksjetall fra rapporten brukes ikke uten separat offisiell avstemming; "
                "valutafordeling av cash gjettes ikke."
            ),
        )
        processed.append(
            {
                "message_id": message_id,
                "status": "applied",
                "report_document_id": report_doc_id,
                "archive": archive,
                "facts": _facts_for_json(facts),
                "apply": applied_result,
            }
        )

    return {
        "status": "ok" if review_required == 0 else ("partial" if applied or ignored else "review_required"),
        "parser_version": REPORT_PARSER_VERSION,
        "candidates": len(candidates),
        "processed": len(processed),
        "applied": applied,
        "ignored": ignored,
        "review_required": review_required,
        "results": processed,
    }
