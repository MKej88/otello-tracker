from __future__ import annotations

import asyncio
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable

from pypdf import PdfReader

try:
    from .newsweb_buybacks import (
        BUYBACK_TITLE,
        DEFAULT_BACKFILL_START,
        BuybackStatus,
        decimal_text,
        normalize_weekly_body,
        parse_newsweb_weekly_status,
    )
    from .newsweb_client import (
        NewsWebAttachment,
        NewsWebMessage,
        attachment_url,
        discover_otec_messages,
        fetch_attachment,
        fetch_message,
    )
    from .r2_archive import archive_bytes
except ImportError:
    from newsweb_buybacks import (
        BUYBACK_TITLE,
        DEFAULT_BACKFILL_START,
        BuybackStatus,
        decimal_text,
        normalize_weekly_body,
        parse_newsweb_weekly_status,
    )
    from newsweb_client import (
        NewsWebAttachment,
        NewsWebMessage,
        attachment_url,
        discover_otec_messages,
        fetch_attachment,
        fetch_message,
    )
    from r2_archive import archive_bytes

RECONCILIATION_LOOKBACK_DAYS = 45
MESSAGE_FETCH_CONCURRENCY = 6
RECONCILIATION_MIN_TOLERANCE_NOK = Decimal("1.00")
RECONCILIATION_RELATIVE_TOLERANCE = Decimal("0.00001")
AVERAGE_PRICE_TOLERANCE_NOK = Decimal("0.02")
PARSER_VERSION = "newsweb-otec-transactions-v5-missing-date-recovery"

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

    payload = normalized
    for match in sorted((date_match, time_match), key=lambda item: item.start(), reverse=True):
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

    if not candidates:
        raise ValueError(f"Kunne ikke avstemme NewsWeb-handelslinje: {normalized}")

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
        raise ValueError(f"Tvetydig NewsWeb-handelslinje; krever kontroll: {normalized}")
    shares, price, amount = selected_pool[0]
    return BuybackTrade(
        trade_date=_date(date_match.group(0)),
        trade_time=time_match.group(0),
        shares=shares,
        price_nok=price,
        amount_nok=amount,
    )


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
    trades = [
        parsed
        for line in text.splitlines()
        if (parsed := _parse_trade_line(line)) is not None
    ]
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
                text,
                trades,
                exec_buys,
                period_start=period_start,
                period_end=period_end,
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
    text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages
    )
    if not text.strip():
        raise ValueError("NewsWeb PDF inneholder ingen lesbar tekst")
    return text


def validate_daily_buybacks(
    daily: list[DailyBuybackTransaction],
    weekly: BuybackStatus,
) -> dict[str, Any]:
    if not daily:
        raise ValueError("Ingen daglige buyback-transaksjoner å validere")
    if any(
        item.trade_date < weekly.period_start or item.trade_date > weekly.period_end
        for item in daily
    ):
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
            "NewsWeb daglig vektet snittkurs avviker fra ukesmelding: "
            f"{weighted} vs {weekly.period_avg_price_nok}"
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


def _has_transaction_name_hint(attachment: NewsWebAttachment) -> bool:
    name = attachment.name.lower().strip()
    return "transaksjonsoversikt" in name or "transaction" in name


def _attachment_candidates(message: NewsWebMessage) -> list[NewsWebAttachment]:
    """Return all NewsWeb attachments, preferring familiar transaction-PDF names.

    NewsWeb has changed attachment filenames over time. The attachment endpoint itself
    validates PDF bytes, and the parser later reconciles shares/amount/price to the
    canonical weekly status, so filename matching is only a priority hint.
    """

    def priority(item: NewsWebAttachment) -> tuple[int, int, int]:
        name = item.name.lower().strip()
        return (
            0 if _has_transaction_name_hint(item) else 1,
            0 if name.endswith(".pdf") else 1,
            item.attachment_id,
        )

    return sorted(message.attachments, key=priority)


async def _weekly_buyback_row(repository, parsed: BuybackStatus) -> dict[str, Any]:
    row = await repository.first(
        """
        SELECT b.id, b.period_start, b.trade_date, b.shares, b.avg_price_nok,
               b.amount_nok, b.cumulative_program_shares,
               b.cumulative_program_avg_price_nok, b.cumulative_program_amount_nok,
               b.treasury_shares_after, b.source_document_id,
               p.external_program_id, p.max_shares
        FROM buybacks b
        JOIN buyback_programs p ON p.id=b.program_id
        WHERE p.external_program_id=? AND b.trade_date=?
        ORDER BY b.id LIMIT 1
        """,
        (parsed.program_external_id, parsed.period_end),
    )
    if row is None:
        raise ValueError(
            f"Mangler kanonisk ukes-buyback for {parsed.program_external_id}/{parsed.period_end}"
        )
    expected = {
        "period_start": parsed.period_start,
        "shares": parsed.period_shares,
        "avg_price_nok": decimal_text(parsed.period_avg_price_nok),
        "amount_nok": decimal_text(parsed.period_amount_nok),
        "cumulative_program_shares": parsed.cumulative_program_shares,
        "cumulative_program_avg_price_nok": decimal_text(
            parsed.cumulative_program_avg_price_nok
        ),
        "cumulative_program_amount_nok": decimal_text(parsed.cumulative_program_amount_nok),
        "treasury_shares_after": parsed.treasury_shares_after,
        "max_shares": parsed.max_program_shares,
    }
    mismatches = [
        f"{key}: lagret={row.get(key)}, melding={value}"
        for key, value in expected.items()
        if str(row.get(key)) != str(value)
    ]
    if mismatches:
        raise ValueError(
            "NewsWeb PDF kan ikke brukes fordi ukesmeldingen avviker fra kanoniske fakta: "
            + "; ".join(mismatches)
        )
    return row


async def _store_daily_rows(
    repository,
    *,
    weekly_buyback_id: int,
    attachment_document_id: int,
    message: NewsWebMessage,
    attachment: NewsWebAttachment,
    daily: list[DailyBuybackTransaction],
    validation: dict[str, Any],
    r2_key: str,
) -> int:
    written = 0
    existing_rows = await repository.all(
        """
        SELECT id, trade_date, shares, avg_price_nok, amount_nok, trade_count
        FROM buyback_daily_transactions
        WHERE weekly_buyback_id=?
        ORDER BY trade_date, id
        """,
        (weekly_buyback_id,),
    )
    existing_by_date: dict[str, dict[str, Any]] = {}
    for row in existing_rows:
        existing_by_date.setdefault(str(row["trade_date"]), row)

    for item in daily:
        metadata = {
            "newsweb_message_id": message.message_id,
            "newsweb_attachment_id": attachment.attachment_id,
            "attachment_name": attachment.name,
            "r2_key": r2_key,
            "weekly_reconciliation": validation,
            "parser": PARSER_VERSION,
        }
        existing = existing_by_date.get(item.trade_date)
        if existing is not None:
            economic_match = (
                int(existing["shares"]) == item.shares
                and Decimal(str(existing["avg_price_nok"])) == item.avg_price_nok
                and Decimal(str(existing["amount_nok"])) == item.amount_nok
                and int(existing["trade_count"]) == item.trade_count
            )
            if not economic_match:
                raise ValueError(
                    f"NewsWeb daglig buyback {item.trade_date} avviker fra lagrede fakta; krever kontroll"
                )
            await repository.run(
                """
                UPDATE buyback_daily_transactions
                SET source_document_id=?, quality=?, metadata_json=?,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=?
                """,
                (
                    attachment_document_id,
                    validation["quality"],
                    __import__("json").dumps(metadata, ensure_ascii=False, sort_keys=True),
                    int(existing["id"]),
                ),
            )
            continue
        await repository.run(
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
                __import__("json").dumps(metadata, ensure_ascii=False, sort_keys=True),
            ),
        )
        written += 1
    return written


async def sync_daily_buyback_cash(repository, *, weekly_buyback_id: int) -> dict[str, Any]:
    week = await repository.first(
        """
        SELECT b.id AS buyback_id, b.trade_date AS period_end, b.shares AS weekly_shares
        FROM buybacks b WHERE b.id=? LIMIT 1
        """,
        (weekly_buyback_id,),
    )
    if week is None:
        raise ValueError(f"Ukjent weekly_buyback_id={weekly_buyback_id}")
    rows = await repository.all(
        """
        SELECT trade_date, shares, amount_nok, source_document_id, quality
        FROM buyback_daily_transactions
        WHERE weekly_buyback_id=?
        ORDER BY trade_date, id
        """,
        (weekly_buyback_id,),
    )
    if not rows:
        return {"weeks_synced": 0, "daily_rows": 0}
    if sum(int(row["shares"]) for row in rows) != int(week["weekly_shares"]):
        raise ValueError("NewsWeb cash-sync nekter uke: daglige aksjer avviker fra ukesrad")
    if any(row["quality"] == "REQUIRES_REVIEW" for row in rows):
        raise ValueError("NewsWeb cash-sync nekter uke: minst én daglig rad krever kontroll")

    weekly_rows = await repository.all(
        """
        SELECT id FROM cash_movements
        WHERE movement_type='OTELLO_BUYBACK'
          AND (buyback_id=? OR (buyback_id IS NULL AND movement_date=?))
        """,
        (weekly_buyback_id, str(week["period_end"])),
    )
    for row in weekly_rows:
        await repository.run("DELETE FROM cash_movements WHERE id=?", (int(row["id"]),))

    daily_cash_rows = await repository.all(
        """
        SELECT id, movement_date FROM cash_movements
        WHERE movement_type='OTELLO_BUYBACK_DAILY' AND buyback_id=?
        ORDER BY movement_date, id
        """,
        (weekly_buyback_id,),
    )
    existing_by_date: dict[str, dict[str, Any]] = {}
    for cash_row in daily_cash_rows:
        existing_by_date.setdefault(str(cash_row["movement_date"]), cash_row)

    seen_dates: set[str] = set()
    written = 0
    updated = 0
    for row in rows:
        trade_date = str(row["trade_date"])
        if trade_date in seen_dates:
            raise ValueError(f"Flere NewsWeb daily-rader for samme uke/dato: {trade_date}")
        seen_dates.add(trade_date)
        amount = decimal_text(-Decimal(str(row["amount_nok"])))
        description = (
            f"NewsWeb transaction-level Otello buyback: {int(row['shares']):,} shares "
            f"on {trade_date}; weekly status period ending {week['period_end']}."
        )
        existing = existing_by_date.get(trade_date)
        if existing is None:
            await repository.run(
                """
                INSERT INTO cash_movements(
                    movement_date, movement_type, amount_nok, amount_original,
                    currency, fx_rate_to_nok, description, source_document_id,
                    confidence, buyback_id
                ) VALUES (?, 'OTELLO_BUYBACK_DAILY', ?, ?, 'NOK', '1', ?, ?, 'CONFIRMED', ?)
                """,
                (
                    trade_date,
                    amount,
                    amount,
                    description,
                    int(row["source_document_id"]),
                    weekly_buyback_id,
                ),
            )
            written += 1
        else:
            await repository.run(
                """
                UPDATE cash_movements
                SET amount_nok=?, amount_original=?, description=?,
                    source_document_id=?, confidence='CONFIRMED'
                WHERE id=?
                """,
                (
                    amount,
                    amount,
                    description,
                    int(row["source_document_id"]),
                    int(existing["id"]),
                ),
            )
            updated += 1

    removed = 0
    for row in daily_cash_rows:
        if str(row["movement_date"]) not in seen_dates:
            await repository.run("DELETE FROM cash_movements WHERE id=?", (int(row["id"]),))
            removed += 1
    return {
        "weeks_synced": 1,
        "weekly_cash_rows_deleted": len(weekly_rows),
        "daily_cash_rows_written": written,
        "daily_cash_rows_updated": updated,
        "stale_daily_cash_rows_deleted": removed,
        "daily_rows": len(rows),
    }


async def _ingest_message(
    repository,
    bucket,
    message: NewsWebMessage,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None,
) -> dict[str, Any]:
    normalized = normalize_weekly_body(message.body)
    if _NO_PURCHASE_RE.search(normalized):
        return {
            "status": "ok",
            "message_id": message.message_id,
            "daily_status": "NO_PURCHASES",
            "daily_rows_written": 0,
            "attachment_candidates": [
                {"id": item.attachment_id, "name": item.name} for item in message.attachments
            ],
        }

    parsed = parse_newsweb_weekly_status(normalized)
    weekly = await _weekly_buyback_row(repository, parsed)
    candidates = _attachment_candidates(message)
    candidate_log = [{"id": item.attachment_id, "name": item.name} for item in candidates]
    if not candidates:
        return {
            "status": "ok",
            "message_id": message.message_id,
            "buyback_id": int(weekly["id"]),
            "daily_status": "NO_TRANSACTION_ATTACHMENT",
            "daily_rows_written": 0,
            "attachment_candidates": [],
        }

    attempts: list[dict[str, Any]] = []
    for attachment in candidates:
        try:
            pdf = await fetch_attachment(
                message.message_id,
                attachment.attachment_id,
                fetcher=fetcher,
            )
            daily = parse_buyback_transaction_text(
                extract_pdf_text(pdf),
                period_start=parsed.period_start,
                period_end=parsed.period_end,
            )
            validation = validate_daily_buybacks(daily, parsed)
        except Exception as exc:
            attempts.append(
                {
                    "id": attachment.attachment_id,
                    "name": attachment.name,
                    "error": str(exc)[:500],
                }
            )
            continue

        logical_date = str(message.published_at)[:10] or parsed.period_end
        archived = await archive_bytes(
            bucket,
            pdf,
            source="newsweb",
            kind="buyback-pdf",
            logical_date=logical_date,
            filename=attachment.name or f"attachment-{attachment.attachment_id}.pdf",
        )
        document_id = await repository.create_source_document(
            source_code="NEWSWEB",
            external_id=f"newsweb-attachment:{message.message_id}:{attachment.attachment_id}",
            document_type="BUYBACK_TRANSACTION_ATTACHMENT",
            title=attachment.name or f"NewsWeb attachment {attachment.attachment_id}",
            url=attachment_url(message.message_id, attachment.attachment_id),
            published_at=message.published_at,
            content_sha256=archived["content_sha256"],
            metadata={
                "newsweb_message_id": message.message_id,
                "newsweb_attachment_id": attachment.attachment_id,
                "filename": attachment.name,
                "parent_weekly_source_document_id": int(weekly["source_document_id"]),
                "parser": PARSER_VERSION,
                "attachment_selection": (
                    "NAME_HINT" if _has_transaction_name_hint(attachment)
                    else "CONTENT_RECONCILIATION_FALLBACK"
                ),
                "attachment_candidates": candidate_log,
                "attachment_attempts_before_match": attempts,
                "weekly_reconciliation": validation,
                "r2_key": archived["r2_key"],
                "r2_bytes": archived["bytes"],
                "archive_policy": "CONTENT_ADDRESSED_R2",
            },
        )
        written = await _store_daily_rows(
            repository,
            weekly_buyback_id=int(weekly["id"]),
            attachment_document_id=document_id,
            message=message,
            attachment=attachment,
            daily=daily,
            validation=validation,
            r2_key=archived["r2_key"],
        )
        cash = await sync_daily_buyback_cash(repository, weekly_buyback_id=int(weekly["id"]))
        return {
            "status": "ok",
            "message_id": message.message_id,
            "buyback_id": int(weekly["id"]),
            "attachment_id": attachment.attachment_id,
            "attachment": attachment.name,
            "attachment_selection": (
                "NAME_HINT" if _has_transaction_name_hint(attachment)
                else "CONTENT_RECONCILIATION_FALLBACK"
            ),
            "attachment_candidates": candidate_log,
            "attachment_attempts_before_match": attempts,
            "attachment_sha256": archived["content_sha256"],
            "r2_key": archived["r2_key"],
            "r2_bytes": archived["bytes"],
            "daily_status": validation["quality"],
            "daily_rows": len(daily),
            "daily_rows_written": written,
            "daily_reconciliation": validation,
            "cash_sync": cash,
        }

    attempted = "; ".join(
        f"{item['id']}:{item['name'] or '<uten navn>'} -> {item['error']}" for item in attempts
    )
    raise ValueError(
        f"NewsWeb-melding {message.message_id} har {len(candidates)} vedlegg, men ingen kunne "
        f"avstemmes som transaksjons-PDF mot ukemeldingen. Forsøk: {attempted}"
    )


async def _fetch_discovered_messages(
    discovered: list[Any],
    *,
    fetcher: Callable[..., Awaitable[Any]] | None,
) -> list[NewsWebMessage | Exception]:
    """Hent meldingsdetaljer parallelt, men med skånsom begrensning."""
    semaphore = asyncio.Semaphore(MESSAGE_FETCH_CONCURRENCY)

    async def fetch_one(item: Any) -> NewsWebMessage | Exception:
        try:
            async with semaphore:
                return await fetch_message(item.message_id, fetcher=fetcher)
        except Exception as exc:
            return exc

    return await asyncio.gather(*(fetch_one(item) for item in discovered))


async def enrich_newsweb_buybacks_with_r2(
    repository,
    bucket,
    *,
    target_date: str,
    lookback_days: int = RECONCILIATION_LOOKBACK_DAYS,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    existing = await repository.first(
        "SELECT MAX(trade_date) AS latest_date FROM buyback_daily_transactions"
    )
    latest = str(existing["latest_date"]) if existing and existing.get("latest_date") else None
    if latest:
        overlap = date.fromisoformat(latest) - timedelta(days=max(21, lookback_days))
        start = max(date.fromisoformat(DEFAULT_BACKFILL_START), overlap).isoformat()
    else:
        start = DEFAULT_BACKFILL_START

    discovered = await discover_otec_messages(
        start,
        target_date,
        message_title=BUYBACK_TITLE,
        fetcher=fetcher,
    )
    messages = await _fetch_discovered_messages(discovered, fetcher=fetcher)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for item, message in zip(discovered, messages, strict=True):
        try:
            if isinstance(message, Exception):
                raise message
            results.append(
                await _ingest_message(
                    repository,
                    bucket,
                    message,
                    fetcher=fetcher,
                )
            )
        except Exception as exc:
            errors.append(
                {
                    "message_id": item.message_id,
                    "published_at": item.published_at,
                    "title": item.title,
                    "error": str(exc)[:1000],
                }
            )

    archived = [item for item in results if item.get("r2_key")]
    status = "error" if errors and not results else ("partial" if errors else "ok")
    return {
        "status": status,
        "from": start,
        "to": target_date,
        "discovered": len(discovered),
        "processed": len(results),
        "pdfs_archived": len(archived),
        "archive_bytes": sum(int(item.get("r2_bytes") or 0) for item in archived),
        "daily_rows": sum(int(item.get("daily_rows") or 0) for item in results),
        "daily_rows_written": sum(
            int(item.get("daily_rows_written") or 0) for item in results
        ),
        "cash_weeks_synced": sum(
            int((item.get("cash_sync") or {}).get("weeks_synced") or 0) for item in results
        ),
        "no_attachment_count": sum(
            item.get("daily_status") == "NO_TRANSACTION_ATTACHMENT" for item in results
        ),
        "no_purchase_count": sum(
            item.get("daily_status") == "NO_PURCHASES" for item in results
        ),
        "parser": PARSER_VERSION,
        "results": results,
        "errors": errors,
    }
