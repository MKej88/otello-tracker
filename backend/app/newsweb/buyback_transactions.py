from __future__ import annotations

import hashlib
import io
import json
import re
from collections import defaultdict
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
RECONCILIATION_RELATIVE_TOLERANCE = Decimal("0.00001")  # 0.001% of weekly consideration
AVERAGE_PRICE_TOLERANCE_NOK = Decimal("0.02")

_TRADE_RE = re.compile(
    r"^B\s+OTEC\s+"
    r"(?P<qty>[\d ]+?)\s+"
    r"(?P<price>\d+[,.]\d+)\s+"
    r"(?P<amount>[\d ]+[,.]\d+)\s+"
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})$",
    re.I,
)
_EXEC_BUY_RE = re.compile(r"^ExecBuy\s+([\d ]+)$", re.I)
_SELL_RE = re.compile(r"^S\s+OTEC\b", re.I)


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


def parse_buyback_trade_lines(text: str) -> list[BuybackTrade]:
    """Parse transaction-level OTEC purchases from a NewsWeb attachment text extract."""
    trades: list[BuybackTrade] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.replace("\u00a0", " ").split())
        if not line:
            continue
        if _SELL_RE.match(line):
            raise ValueError("NewsWeb buyback-vedlegg inneholder OTEC-salg; krever kontroll")
        match = _TRADE_RE.match(line)
        if not match:
            continue
        shares = _integer(match.group("qty"))
        price = _decimal(match.group("price"))
        amount = _decimal(match.group("amount"))
        if shares <= 0 or price <= 0 or amount <= 0:
            raise ValueError(f"Ugyldig buyback-transaksjon i NewsWeb: {line}")
        expected = price * Decimal(shares)
        if abs(expected - amount) > Decimal("0.01"):
            raise ValueError(
                f"NewsWeb transaksjon avstemmer ikke: {shares} x {price} != {amount}"
            )
        trades.append(
            BuybackTrade(
                trade_date=_date(match.group("date")),
                trade_time=match.group("time"),
                shares=shares,
                price_nok=price,
                amount_nok=amount,
            )
        )
    if not trades:
        raise ValueError("Fant ingen OTEC-kjøp i NewsWeb-transaksjonsvedlegget")
    return trades


def aggregate_daily_buybacks(trades: list[BuybackTrade]) -> list[DailyBuybackTransaction]:
    grouped: dict[str, list[BuybackTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.trade_date].append(trade)
    result: list[DailyBuybackTransaction] = []
    for trade_date in sorted(grouped):
        day = grouped[trade_date]
        shares = sum(item.shares for item in day)
        amount = sum((item.amount_nok for item in day), Decimal("0"))
        result.append(
            DailyBuybackTransaction(
                trade_date=trade_date,
                shares=shares,
                avg_price_nok=amount / Decimal(shares),
                amount_nok=amount,
                trade_count=len(day),
            )
        )
    return result


def parse_buyback_transaction_text(text: str) -> list[DailyBuybackTransaction]:
    trades = parse_buyback_trade_lines(text)
    daily = aggregate_daily_buybacks(trades)

    # The attachment itself contains one ExecBuy total after each trading day. Comparing
    # those summaries with independently aggregated trade lines catches broken PDF text
    # extraction before any cash model consumes the result.
    exec_buys = [
        _integer(match.group(1))
        for raw in text.splitlines()
        if (match := _EXEC_BUY_RE.match(" ".join(raw.replace("\u00a0", " ").split())))
    ]
    if exec_buys and exec_buys != [item.shares for item in daily]:
        raise ValueError(
            f"NewsWeb ExecBuy-avstemming feilet: vedlegg={exec_buys}, parser={[item.shares for item in daily]}"
        )
    return daily


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("NewsWeb-vedlegg er ikke PDF")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError("NewsWeb PDF inneholder ingen lesbar tekst")
    return text


def validate_daily_buybacks(
    daily: list[DailyBuybackTransaction],
    weekly: BuybackStatus,
) -> dict[str, Any]:
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
    amount_difference = amount - weekly.period_amount_nok
    amount_tolerance = max(
        RECONCILIATION_MIN_TOLERANCE_NOK,
        abs(weekly.period_amount_nok) * RECONCILIATION_RELATIVE_TOLERANCE,
    )
    if abs(amount_difference) > amount_tolerance:
        raise ValueError(
            "NewsWeb daglig beløp avviker fra ukesmelding med "
            f"NOK {amount_difference} (toleranse {amount_tolerance}); krever kontroll"
        )
    weighted_average = amount / Decimal(shares)
    if abs(weighted_average - weekly.period_avg_price_nok) > AVERAGE_PRICE_TOLERANCE_NOK:
        raise ValueError(
            "NewsWeb daglig vektet snittkurs avviker fra ukesmelding: "
            f"{weighted_average} vs {weekly.period_avg_price_nok}"
        )
    return {
        "shares": shares,
        "amount_nok": decimal_text(amount),
        "weekly_amount_nok": decimal_text(weekly.period_amount_nok),
        "amount_difference_nok": decimal_text(amount_difference),
        "amount_tolerance_nok": decimal_text(amount_tolerance),
        "weighted_average_nok": decimal_text(weighted_average),
        "quality": "CONFIRMED" if amount_difference == 0 else "RECONCILED",
    }


def _transaction_attachment(message: NewsWebMessage) -> NewsWebAttachment | None:
    candidates = [
        item
        for item in message.attachments
        if item.name.lower().endswith(".pdf")
        and ("transaksjonsoversikt" in item.name.lower() or "transaction" in item.name.lower())
    ]
    if len(candidates) > 1:
        raise ValueError(
            f"NewsWeb-melding {message.message_id} har flere mulige transaksjonsvedlegg"
        )
    return candidates[0] if candidates else None


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
                "parser": "newsweb-otec-transactions-v1",
            }
            existing = connection.execute(
                """
                SELECT id, shares, avg_price_nok, amount_nok, trade_count, source_document_id
                FROM buyback_daily_transactions
                WHERE weekly_buyback_id = ? AND trade_date = ?
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
                mismatches = [
                    key for key, value in values.items()
                    if str(existing[key]) != str(value)
                ]
                if mismatches:
                    raise ValueError(
                        f"NewsWeb daglig buyback {item.trade_date} avviker fra lagrede fakta ({', '.join(mismatches)}); krever kontroll"
                    )
                connection.execute(
                    """
                    UPDATE buyback_daily_transactions
                    SET source_document_id = ?, quality = ?, metadata_json = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (
                        attachment_document_id,
                        validation["quality"],
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                        existing["id"],
                    ),
                )
                continue
            connection.execute(
                """
                INSERT INTO buyback_daily_transactions(
                    weekly_buyback_id, trade_date, shares, avg_price_nok, amount_nok,
                    trade_count, source_document_id, quality, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    weekly_buyback_id,
                    item.trade_date,
                    item.shares,
                    decimal_text(item.avg_price_nok),
                    decimal_text(item.amount_nok),
                    item.trade_count,
                    attachment_document_id,
                    validation["quality"],
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            written += 1
        connection.commit()
    return written


def ingest_newsweb_buyback_message(
    message_id: int,
    database_path: str | None = None,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    message = fetch_message(message_id, timeout=timeout)
    if BUYBACK_TITLE not in message.title.lower():
        raise ValueError(f"NewsWeb-melding {message_id} er ikke en buyback-status")
    weekly = parse_euronext_buyback_status(message.body)
    weekly_result = ingest_buyback_status(
        parsed=weekly,
        url=message.public_url,
        published_at=message.published_at,
        database_path=database_path,
        source_code="NEWSWEB",
        source_metadata={
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
        },
        content_hash=hashlib.sha256(message.body.encode("utf-8")).hexdigest(),
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
        }

    pdf_bytes = fetch_attachment(message.message_id, attachment.attachment_id, timeout=timeout)
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    text = extract_pdf_text(pdf_bytes)
    daily = parse_buyback_transaction_text(text)
    validation = validate_daily_buybacks(daily, weekly)

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
                "parser": "pypdf + deterministic OTEC transaction parser",
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
    }


def _default_from_date(database_path: str | None, to_date: str) -> str:
    with get_connection(database_path) as connection:
        latest = connection.execute(
            "SELECT MAX(trade_date) AS max_date FROM buyback_daily_transactions"
        ).fetchone()["max_date"]
    if not latest:
        return DEFAULT_BACKFILL_START
    return max(
        date.fromisoformat(DEFAULT_BACKFILL_START),
        date.fromisoformat(latest) - timedelta(days=21),
    ).isoformat()


def collect_newsweb_buybacks(
    database_path: str | None = None,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    end = to_date or date.today().isoformat()
    start = from_date or _default_from_date(database_path, end)
    discovered = discover_otec_messages(
        start,
        end,
        message_title=BUYBACK_TITLE,
        timeout=timeout,
    )
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for item in discovered:
        try:
            results.append(
                ingest_newsweb_buyback_message(item.message_id, database_path, timeout=timeout)
            )
        except Exception as exc:
            errors.append(
                {
                    "message_id": item.message_id,
                    "published_at": item.published_at,
                    "title": item.title,
                    "error": str(exc),
                }
            )
    return {
        "status": "ok" if results and not errors else ("partial" if results else "error"),
        "source": "Oslo Børs NewsWeb",
        "issuer_id": 7759,
        "from": start,
        "to": end,
        "discovered": len(discovered),
        "ingested": len(results),
        "daily_rows": sum(int(item.get("daily_rows", 0)) for item in results),
        "daily_rows_written": sum(int(item.get("daily_rows_written", 0)) for item in results),
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
        covered = connection.execute(
            "SELECT COUNT(DISTINCT weekly_buyback_id) n FROM buyback_daily_transactions"
        ).fetchone()["n"]
        weekly = connection.execute("SELECT COUNT(*) n FROM buybacks").fetchone()["n"]
        latest = connection.execute(
            """
            SELECT d.trade_date, d.shares, d.avg_price_nok, d.amount_nok,
                   d.trade_count, d.quality, b.trade_date weekly_period_end
            FROM buyback_daily_transactions d
            JOIN buybacks b ON b.id = d.weekly_buyback_id
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
