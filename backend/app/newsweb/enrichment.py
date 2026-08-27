from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pypdf import PdfReader

from app.buybacks.euronext import BuybackStatus, ingest_buyback_status, parse_euronext_buyback_status
from app.db.connection import get_connection
from app.db.repository import create_source_document, decimal_text
from app.newsweb.client import (
    NewsWebAttachment,
    NewsWebMessage,
    attachment_url,
    discover_otec_messages,
    fetch_attachment,
    fetch_message,
)

BUYBACK_TITLE = "share buyback program status"
DEFAULT_BACKFILL_START = "2024-07-01"
RECONCILIATION_MIN_TOLERANCE_NOK = Decimal("1.00")
RECONCILIATION_RELATIVE_TOLERANCE = Decimal("0.00001")
AVERAGE_PRICE_TOLERANCE_NOK = Decimal("0.02")

_DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_TIME_RE = re.compile(r"\d{2}:\d{2}:\d{2}")
_EXEC_BUY_RE = re.compile(r"^ExecBuy\s+([\d \u00a0]+)$", re.I)
_SELL_RE = re.compile(r"^S\s+OTEC\b", re.I)
_NO_PURCHASE_RE = re.compile(
    r"From (\d{1,2} [A-Za-z]+ \d{4}) through (\d{1,2} [A-Za-z]+ \d{4}),"
    r".*?did not buy any shares",
    re.I,
)


@dataclass(frozen=True)
class BuybackTrade:
    trade_date: str
    trade_time: str
    shares: int
    price_nok: Decimal
    amount_nok: Decimal


@dataclass(frozen=True)
class DailyBuybackTransaction:
    trade_date: str
    shares: int
    avg_price_nok: Decimal
    amount_nok: Decimal
    trade_count: int


def _integer(value: str) -> int:
    return int(value.replace(" ", "").replace("\u00a0", ""))


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def _date(value: str) -> str:
    day, month, year = value.split(".")
    return date(int(year), int(month), int(day)).isoformat()


def _normalize_weekly_body(text: str) -> str:
    """Normalize documented Otello wording/decimal variants before strict weekly parsing."""
    clean = " ".join(text.split())
    clean = clean.replace(
        "announcing a share buyback program",
        "announcing the initiation of the share buyback program",
    )
    clean = clean.replace(
        "Since the initiation of the share buyback program",
        "Since the initiation of this share buyback program",
    )
    clean = clean.replace(
        "maximum number of shares that can be purchased is",
        "maximum number of shares that can be purchased under this buyback program is",
    )
    # The legacy parser correctly treats comma-separated whole-NOK amounts as thousands,
    # but Otello has occasionally used decimal comma for average prices (e.g. NOK 13,17).
    clean = re.sub(
        r"(average price of NOK\s+)(\d+),(\d{1,4})(?=\s)",
        lambda match: f"{match.group(1)}{match.group(2)}.{match.group(3)}",
        clean,
        flags=re.I,
    )
    return clean


def _parse_trade_line(line: str) -> BuybackTrade | None:
    normalized = " ".join(line.replace("\u00a0", " ").split())
    if not normalized:
        return None
    if _SELL_RE.match(normalized):
        raise ValueError("NewsWeb buyback-vedlegg inneholder OTEC-salg; krever kontroll")
    if not normalized.upper().startswith("B OTEC "):
        return None

    date_match = _DATE_RE.search(normalized)
    time_match = _TIME_RE.search(normalized)
    if date_match is None or time_match is None:
        return None
    trade_date = _date(date_match.group(0))
    trade_time = time_match.group(0)

    # Remove date/time regardless of whether pypdf emitted date-before-time, time-before-date,
    # or glued them directly to the consideration field.
    payload = normalized
    for match in sorted((date_match, time_match), key=lambda item: item.start(), reverse=True):
        payload = payload[: match.start()] + " " + payload[match.end() :]
    payload = " ".join(payload.split())
    tokens = payload[len("B OTEC ") :].split()
    if len(tokens) < 3:
        return None

    # Quantity may contain spaces as thousands separators. The price is normally the first
    # token containing decimal punctuation; newer PDFs can emit integer prices (17), in
    # which case it is the penultimate token and the final token is the integer amount.
    price_index = next(
        (index for index, token in enumerate(tokens[1:], start=1) if "," in token or "." in token),
        None,
    )
    if price_index is None:
        price_index = len(tokens) - 2
    if price_index <= 0 or price_index >= len(tokens) - 1:
        return None

    shares = _integer("".join(tokens[:price_index]))
    price = _decimal(tokens[price_index])
    amount = _decimal("".join(tokens[price_index + 1 :]))
    if shares <= 0 or price <= 0 or amount <= 0:
        raise ValueError(f"Ugyldig buyback-transaksjon i NewsWeb: {normalized}")
    expected = price * Decimal(shares)
    if abs(expected - amount) > Decimal("0.01"):
        raise ValueError(
            f"NewsWeb transaksjon avstemmer ikke: {shares} x {price} != {amount}"
        )
    return BuybackTrade(trade_date, trade_time, shares, price, amount)


def _parse_undated_duplicate_time_line(line: str) -> BuybackTrade | None:
    """Parse only the documented pypdf defect where the date cell repeats the time.

    A date is intentionally not inferred here. The caller may assign one only when
    the canonical weekly period leaves exactly one possible trading day and the
    recovered block reconciles to exactly one missing ExecBuy total.
    """
    normalized = " ".join(line.replace("\u00a0", " ").split())
    if not normalized:
        return None
    if _SELL_RE.match(normalized):
        raise ValueError("NewsWeb buyback-vedlegg inneholder OTEC-salg; krever kontroll")
    if not normalized.upper().startswith("B OTEC ") or _DATE_RE.search(normalized):
        return None
    time_matches = list(_TIME_RE.finditer(normalized))
    if len(time_matches) != 2 or time_matches[0].group(0) != time_matches[1].group(0):
        return None

    payload = normalized
    for match in reversed(time_matches):
        payload = payload[: match.start()] + " " + payload[match.end() :]
    tokens = " ".join(payload.split())[len("B OTEC ") :].split()
    if len(tokens) < 3:
        return None

    candidates: list[tuple[int, Decimal, Decimal]] = []
    for price_index in range(1, len(tokens) - 1):
        try:
            shares = _integer("".join(tokens[:price_index]))
            price = _decimal(tokens[price_index])
            amount = _decimal("".join(tokens[price_index + 1 :]))
        except (ValueError, ArithmeticError):
            continue
        if shares <= 0 or price <= 0 or amount <= 0 or price > Decimal("500"):
            continue
        if abs(Decimal(shares) * price - amount) <= Decimal("0.01"):
            candidates.append((shares, price, amount))

    punctuated: list[tuple[int, Decimal, Decimal]] = []
    for price_index in range(1, len(tokens) - 1):
        if "," not in tokens[price_index] and "." not in tokens[price_index]:
            continue
        try:
            candidate = (
                _integer("".join(tokens[:price_index])),
                _decimal(tokens[price_index]),
                _decimal("".join(tokens[price_index + 1 :])),
            )
        except (ValueError, ArithmeticError):
            continue
        if candidate in candidates:
            punctuated.append(candidate)
    selected_pool = punctuated or list(dict.fromkeys(candidates))
    if len(selected_pool) != 1:
        raise ValueError(
            f"Tvetydig udatert NewsWeb-handelslinje; krever kontroll: {normalized}"
        )
    shares, price, amount = selected_pool[0]
    return BuybackTrade(
        trade_date="",
        trade_time=time_matches[0].group(0),
        shares=shares,
        price_nok=price,
        amount_nok=amount,
    )


def _recover_single_missing_trade_date(
    text: str,
    trades: list[BuybackTrade],
    exec_buys: list[int],
    *,
    period_start: str,
    period_end: str,
) -> list[BuybackTrade]:
    undated = [
        parsed
        for raw in text.splitlines()
        if (parsed := _parse_undated_duplicate_time_line(raw)) is not None
    ]
    if not undated:
        return trades

    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)
    if end < start:
        raise ValueError("Ugyldig NewsWeb-ukesperiode for datoreparasjon")
    weekdays: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            weekdays.append(current.isoformat())
        current += timedelta(days=1)

    known_dates = {item.trade_date for item in trades}
    missing_dates = [item for item in weekdays if item not in known_dates]
    if len(missing_dates) != 1:
        raise ValueError(
            "NewsWeb manglende PDF-dato kan ikke utledes entydig fra ukesperioden"
        )

    parsed_totals = [item.shares for item in aggregate_daily_buybacks(trades)]
    parsed_counter = Counter(parsed_totals)
    exec_counter = Counter(exec_buys)
    if parsed_counter - exec_counter:
        raise ValueError("NewsWeb datoreparasjon avviser ukjent allerede-parset dagsum")
    missing_exec = exec_counter - parsed_counter
    if sum(missing_exec.values()) != 1:
        raise ValueError(
            "NewsWeb datoreparasjon krever nøyaktig én manglende ExecBuy-dagsum"
        )
    expected_shares = next(missing_exec.elements())
    recovered_shares = sum(item.shares for item in undated)
    if recovered_shares != expected_shares:
        raise ValueError(
            "NewsWeb udaterte handler avstemmer ikke mot den manglende ExecBuy-dagsummen"
        )

    inferred_date = missing_dates[0]
    recovered = [
        BuybackTrade(
            trade_date=inferred_date,
            trade_time=item.trade_time,
            shares=item.shares,
            price_nok=item.price_nok,
            amount_nok=item.amount_nok,
        )
        for item in undated
    ]
    return [*trades, *recovered]

def parse_buyback_trade_lines(text: str) -> list[BuybackTrade]:
    trades: list[BuybackTrade] = []
    for line in text.splitlines():
        parsed = _parse_trade_line(line)
        if parsed is not None:
            trades.append(parsed)
    if not trades:
        raise ValueError("Fant ingen OTEC-kjøp i NewsWeb-transaksjonsvedlegget")
    return trades


def aggregate_daily_buybacks(trades: list[BuybackTrade]) -> list[DailyBuybackTransaction]:
    grouped: dict[str, list[BuybackTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.trade_date].append(trade)
    result: list[DailyBuybackTransaction] = []
    for trade_date in sorted(grouped):
        rows = grouped[trade_date]
        shares = sum(row.shares for row in rows)
        amount = sum((row.amount_nok for row in rows), Decimal("0"))
        result.append(
            DailyBuybackTransaction(
                trade_date=trade_date,
                shares=shares,
                avg_price_nok=amount / Decimal(shares),
                amount_nok=amount,
                trade_count=len(rows),
            )
        )
    return result


def parse_buyback_transaction_text(
    text: str,
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[DailyBuybackTransaction]:
    trades = parse_buyback_trade_lines(text)
    daily = aggregate_daily_buybacks(trades)
    exec_buys = [
        _integer(match.group(1))
        for raw in text.splitlines()
        if (match := _EXEC_BUY_RE.match(" ".join(raw.replace("\u00a0", " ").split())))
    ]
    parsed_totals = [item.shares for item in daily]
    if exec_buys and sorted(exec_buys) != sorted(parsed_totals):
        if period_start is not None and period_end is not None:
            trades = _recover_single_missing_trade_date(
                text, trades, exec_buys,
                period_start=period_start, period_end=period_end,
            )
            daily = aggregate_daily_buybacks(trades)
            parsed_totals = [item.shares for item in daily]
    if exec_buys and sorted(exec_buys) != sorted(parsed_totals):
        raise ValueError(
            f"NewsWeb ExecBuy-avstemming feilet: vedlegg={exec_buys}, parser={parsed_totals}"
        )
    return daily


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("NewsWeb-vedlegg er ikke PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    if not text.strip():
        raise ValueError("NewsWeb PDF inneholder ingen lesbar tekst")
    return text


def validate_daily_buybacks(daily: list[DailyBuybackTransaction], weekly: BuybackStatus) -> dict[str, Any]:
    if not daily:
        raise ValueError("Ingen daglige buyback-transaksjoner å validere")
    if any(item.trade_date < weekly.period_start or item.trade_date > weekly.period_end for item in daily):
        raise ValueError("NewsWeb daglige transaksjoner ligger utenfor ukens annonserte periode")
    shares = sum(item.shares for item in daily)
    if shares != weekly.period_shares:
        raise ValueError(
            f"NewsWeb daglige aksjer avviker fra ukesmelding: {shares} != {weekly.period_shares}"
        )
    amount = sum((item.amount_nok for item in daily), Decimal("0"))
    difference = amount - weekly.period_amount_nok
    tolerance = max(
        RECONCILIATION_MIN_TOLERANCE_NOK,
        abs(weekly.period_amount_nok) * RECONCILIATION_RELATIVE_TOLERANCE,
    )
    if abs(difference) > tolerance:
        raise ValueError(
            f"NewsWeb daglig beløp avviker fra ukesmelding med NOK {difference} "
            f"(toleranse {tolerance}); krever kontroll"
        )
    weighted = amount / Decimal(shares)
    if abs(weighted - weekly.period_avg_price_nok) > AVERAGE_PRICE_TOLERANCE_NOK:
        raise ValueError(
            f"NewsWeb daglig vektet snittkurs avviker fra ukesmelding: {weighted} vs {weekly.period_avg_price_nok}"
        )
    return {
        "shares": shares,
        "amount_nok": decimal_text(amount),
        "weekly_amount_nok": decimal_text(weekly.period_amount_nok),
        "amount_difference_nok": decimal_text(difference),
        "amount_tolerance_nok": decimal_text(tolerance),
        "weighted_average_nok": decimal_text(weighted),
        "quality": "CONFIRMED" if difference == 0 else "RECONCILED",
    }


def _transaction_attachment(message: NewsWebMessage) -> NewsWebAttachment | None:
    candidates = [
        item for item in message.attachments
        if item.name.lower().endswith(".pdf")
        and ("transaksjonsoversikt" in item.name.lower() or "transaction" in item.name.lower())
    ]
    if len(candidates) > 1:
        raise ValueError(f"NewsWeb-melding {message.message_id} har flere mulige transaksjonsvedlegg")
    return candidates[0] if candidates else None


def _message_metadata(message: NewsWebMessage) -> dict[str, Any]:
    return {
        "source_quality": "OFFICIAL_ORIGINAL",
        "newsweb_message_id": message.message_id,
        "news_id": message.news_id,
        "issuer_id": message.issuer_id,
        "issuer_sign": message.issuer_sign,
        "markets": list(message.markets),
        "category_ids": list(message.category_ids),
        "client_announcement_id": message.client_announcement_id,
        "correction_for_message_id": message.correction_for_message_id,
        "corrected_by_message_id": message.corrected_by_message_id,
    }


def _store_message_document(message: NewsWebMessage, database_path: str | None, *, metadata: dict[str, Any] | None = None) -> int:
    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id=f"newsweb-message:{message.message_id}",
            document_type="REGULATORY_NEWS",
            title=message.title,
            url=message.public_url,
            published_at=message.published_at,
            content_sha256=hashlib.sha256(message.body.encode("utf-8")).hexdigest(),
            metadata={**_message_metadata(message), **(metadata or {})},
        )
        connection.commit()
    return document_id


def _existing_weekly(database_path: str | None, parsed: BuybackStatus) -> tuple[dict[str, Any], BuybackStatus] | None:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT b.id, b.trade_date, b.shares, b.avg_price_nok, b.amount_nok,
                   b.cumulative_program_shares, b.cumulative_program_avg_price_nok,
                   b.cumulative_program_amount_nok, b.treasury_shares_after,
                   b.source_document_id, p.id program_id, p.external_program_id, p.max_shares
            FROM buybacks b JOIN buyback_programs p ON p.id=b.program_id
            WHERE b.trade_date=? ORDER BY b.id
            """,
            (parsed.period_end,),
        ).fetchall()
    if len(rows) != 1:
        return None
    row = rows[0]
    prefix = "otec-buyback-"
    external = row["external_program_id"] or ""
    if not external.startswith(prefix):
        return None
    status = BuybackStatus(
        program_reference_date=external[len(prefix):],
        period_start=parsed.period_start,
        period_end=row["trade_date"],
        period_shares=int(row["shares"]),
        period_avg_price_nok=Decimal(row["avg_price_nok"]),
        period_amount_nok=Decimal(row["amount_nok"]),
        cumulative_program_shares=int(row["cumulative_program_shares"]),
        cumulative_program_avg_price_nok=Decimal(row["cumulative_program_avg_price_nok"]),
        cumulative_program_amount_nok=Decimal(row["cumulative_program_amount_nok"]),
        max_program_shares=int(row["max_shares"]),
        treasury_shares_after=int(row["treasury_shares_after"]),
    )
    result = {
        "buyback_id": int(row["id"]),
        "program_id": int(row["program_id"]),
        "period_end": row["trade_date"],
        "period_shares": int(row["shares"]),
        "period_amount_nok": row["amount_nok"],
        "cumulative_program_shares": int(row["cumulative_program_shares"]),
        "cumulative_program_avg_price_nok": row["cumulative_program_avg_price_nok"],
        "cumulative_program_amount_nok": row["cumulative_program_amount_nok"],
        "treasury_shares_after": int(row["treasury_shares_after"]),
        "source_code": "EXISTING_STRONGER",
        "source_applied": False,
        "canonical_source_document_id": int(row["source_document_id"]),
    }
    return result, status


def _store_daily_rows(
    database_path: str | None,
    *,
    weekly_buyback_id: int,
    attachment_document_id: int,
    message: NewsWebMessage,
    attachment: NewsWebAttachment,
    daily: list[DailyBuybackTransaction],
    validation: dict[str, Any],
) -> int:
    written = 0
    with get_connection(database_path) as connection:
        for item in daily:
            metadata = {
                "newsweb_message_id": message.message_id,
                "newsweb_attachment_id": attachment.attachment_id,
                "attachment_name": attachment.name,
                "weekly_reconciliation": validation,
                "parser": "newsweb-otec-transactions-v3-missing-date-recovery",
            }
            existing = connection.execute(
                """
                SELECT id, shares, avg_price_nok, amount_nok, trade_count
                FROM buyback_daily_transactions
                WHERE weekly_buyback_id=? AND trade_date=?
                """,
                (weekly_buyback_id, item.trade_date),
            ).fetchone()
            values = {
                "shares": item.shares,
                "avg_price_nok": decimal_text(item.avg_price_nok),
                "amount_nok": decimal_text(item.amount_nok),
                "trade_count": item.trade_count,
            }
            if existing is not None:
                mismatches = [key for key, value in values.items() if str(existing[key]) != str(value)]
                if mismatches:
                    raise ValueError(
                        f"NewsWeb daglig buyback {item.trade_date} avviker fra lagrede fakta ({', '.join(mismatches)}); krever kontroll"
                    )
                connection.execute(
                    """
                    UPDATE buyback_daily_transactions
                    SET source_document_id=?, quality=?, metadata_json=?,
                        updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?
                    """,
                    (
                        attachment_document_id, validation["quality"],
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True), existing["id"],
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO buyback_daily_transactions(
                        weekly_buyback_id, trade_date, shares, avg_price_nok, amount_nok,
                        trade_count, source_document_id, quality, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        weekly_buyback_id, item.trade_date, item.shares,
                        decimal_text(item.avg_price_nok), decimal_text(item.amount_nok),
                        item.trade_count, attachment_document_id, validation["quality"],
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )
                written += 1
        connection.commit()
    return written


def ingest_newsweb_buyback_message(message_id: int, database_path: str | None = None, *, timeout: int = 30) -> dict[str, Any]:
    message = fetch_message(message_id, timeout=timeout)
    if BUYBACK_TITLE not in message.title.lower():
        raise ValueError(f"NewsWeb-melding {message_id} er ikke en buyback-status")

    normalized_body = _normalize_weekly_body(message.body)
    no_purchase = _NO_PURCHASE_RE.search(normalized_body)
    if no_purchase:
        document_id = _store_message_document(
            message, database_path,
            metadata={"buyback_status": "NO_PURCHASES", "period_text": no_purchase.group(0)},
        )
        return {
            "message_id": message.message_id,
            "canonical_source_document_id": document_id,
            "daily_rows_written": 0,
            "daily_rows": 0,
            "attachment": None,
            "daily_status": "NO_PURCHASES",
            "warning": None,
        }

    weekly_from_body = parse_euronext_buyback_status(normalized_body)
    weekly_for_validation = weekly_from_body
    weekly_warning: str | None = None
    try:
        weekly_result = ingest_buyback_status(
            parsed=weekly_from_body,
            url=message.public_url,
            published_at=message.published_at,
            database_path=database_path,
            source_code="NEWSWEB",
            source_metadata=_message_metadata(message),
            content_hash=hashlib.sha256(message.body.encode("utf-8")).hexdigest(),
        )
    except ValueError as exc:
        existing = _existing_weekly(database_path, weekly_from_body)
        if existing is None:
            raise
        weekly_result, weekly_for_validation = existing
        weekly_warning = (
            "NewsWeb weekly prose differed from an existing stronger curated/official row; "
            f"daily attachment is validated against the existing row. Detail: {exc}"
        )
        _store_message_document(
            message, database_path,
            metadata={"weekly_source_discrepancy": True, "weekly_discrepancy_note": str(exc)},
        )

    attachment = _transaction_attachment(message)
    if attachment is None:
        return {
            **weekly_result,
            "message_id": message.message_id,
            "daily_rows_written": 0,
            "daily_rows": 0,
            "attachment": None,
            "daily_status": "NO_TRANSACTION_ATTACHMENT",
            "warning": weekly_warning,
        }

    try:
        pdf_bytes = fetch_attachment(message.message_id, attachment.attachment_id, timeout=timeout)
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
        daily = parse_buyback_transaction_text(
            extract_pdf_text(pdf_bytes),
            period_start=weekly_for_validation.period_start,
            period_end=weekly_for_validation.period_end,
        )
        validation = validate_daily_buybacks(daily, weekly_for_validation)

        with get_connection(database_path) as connection:
            attachment_document_id = create_source_document(
                connection,
                source_code="NEWSWEB",
                external_id=f"newsweb-attachment:{message.message_id}:{attachment.attachment_id}",
                document_type="BUYBACK_TRANSACTION_ATTACHMENT",
                title=attachment.name,
                url=attachment_url(message.message_id, attachment.attachment_id),
                published_at=message.published_at,
                content_sha256=pdf_hash,
                metadata={
                    "newsweb_message_id": message.message_id,
                    "newsweb_attachment_id": attachment.attachment_id,
                    "filename": attachment.name,
                    "parent_message_document_id": weekly_result["canonical_source_document_id"],
                    "parser": "pypdf + deterministic OTEC transaction parser v3 missing-date recovery",
                    "weekly_reconciliation": validation,
                },
            )
            connection.commit()

        written = _store_daily_rows(
            database_path,
            weekly_buyback_id=weekly_result["buyback_id"],
            attachment_document_id=attachment_document_id,
            message=message,
            attachment=attachment,
            daily=daily,
            validation=validation,
        )
        return {
            **weekly_result,
            "message_id": message.message_id,
            "daily_rows_written": written,
            "daily_rows": len(daily),
            "attachment": attachment.name,
            "attachment_id": attachment.attachment_id,
            "attachment_sha256": pdf_hash,
            "daily_status": validation["quality"],
            "daily_reconciliation": validation,
            "warning": weekly_warning,
        }
    except Exception as exc:
        # Weekly facts remain usable and Phase 9.2 cash timing remains the conservative
        # fallback. An attachment-format/source discrepancy must be visible, but should
        # not make the whole historical refresh fail or replace the weekly cash summary.
        return {
            **weekly_result,
            "message_id": message.message_id,
            "daily_rows_written": 0,
            "daily_rows": 0,
            "attachment": attachment.name,
            "attachment_id": attachment.attachment_id,
            "daily_status": "ATTACHMENT_REQUIRES_REVIEW",
            "warning": "; ".join(filter(None, (weekly_warning, str(exc)))),
        }


def _default_from_date(database_path: str | None) -> str:
    with get_connection(database_path) as connection:
        latest = connection.execute("SELECT MAX(trade_date) max_date FROM buyback_daily_transactions").fetchone()["max_date"]
    if not latest:
        return DEFAULT_BACKFILL_START
    return max(date.fromisoformat(DEFAULT_BACKFILL_START), date.fromisoformat(latest) - timedelta(days=21)).isoformat()


def collect_newsweb_buybacks(
    database_path: str | None = None,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    end = to_date or date.today().isoformat()
    start = from_date or _default_from_date(database_path)
    discovered = discover_otec_messages(start, end, message_title=BUYBACK_TITLE, timeout=timeout)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for item in discovered:
        try:
            results.append(ingest_newsweb_buyback_message(item.message_id, database_path, timeout=timeout))
        except Exception as exc:
            errors.append({
                "message_id": item.message_id,
                "published_at": item.published_at,
                "title": item.title,
                "error": str(exc),
            })
    warnings = [
        {
            "message_id": item.get("message_id"),
            "daily_status": item.get("daily_status"),
            "warning": item.get("warning"),
        }
        for item in results if item.get("warning")
    ]
    daily_rows = sum(int(item.get("daily_rows", 0)) for item in results)
    return {
        "status": "error" if errors and not results else ("partial" if errors else "ok"),
        "source": "Oslo Børs NewsWeb",
        "issuer_id": 7759,
        "from": start,
        "to": end,
        "discovered": len(discovered),
        "ingested": len(results),
        "daily_rows": daily_rows,
        "daily_rows_written": sum(int(item.get("daily_rows_written", 0)) for item in results),
        "attachment_review_count": sum(item.get("daily_status") == "ATTACHMENT_REQUIRES_REVIEW" for item in results),
        "no_attachment_count": sum(item.get("daily_status") == "NO_TRANSACTION_ATTACHMENT" for item in results),
        "no_purchase_count": sum(item.get("daily_status") == "NO_PURCHASES" for item in results),
        "warnings": warnings,
        "results": results,
        "errors": errors,
    }


def newsweb_buyback_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        aggregate = connection.execute(
            """
            SELECT COUNT(*) n, MIN(trade_date) min_date, MAX(trade_date) max_date,
                   SUM(shares) shares, SUM(CAST(amount_nok AS REAL)) amount_nok
            FROM buyback_daily_transactions
            """
        ).fetchone()
        covered = connection.execute("SELECT COUNT(DISTINCT weekly_buyback_id) n FROM buyback_daily_transactions").fetchone()["n"]
        weekly = connection.execute("SELECT COUNT(*) n FROM buybacks").fetchone()["n"]
        latest = connection.execute(
            """
            SELECT d.trade_date, d.shares, d.avg_price_nok, d.amount_nok,
                   d.trade_count, d.quality, b.trade_date weekly_period_end
            FROM buyback_daily_transactions d JOIN buybacks b ON b.id=d.weekly_buyback_id
            ORDER BY d.trade_date DESC, d.id DESC LIMIT 1
            """
        ).fetchone()
    return {
        "status": "ok" if aggregate["n"] else "empty",
        "count": aggregate["n"],
        "from": aggregate["min_date"],
        "to": aggregate["max_date"],
        "shares": aggregate["shares"],
        "amount_nok": aggregate["amount_nok"],
        "weekly_buybacks_with_daily_detail": covered,
        "weekly_buybacks_total": weekly,
        "latest": dict(latest) if latest is not None else None,
    }
