from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable

from newsweb_client import NewsWebMessage, discover_otec_messages, fetch_message
from repository import D1WriteRepository

BUYBACK_TITLE = "share buyback program status"
DEFAULT_BACKFILL_START = "2024-07-01"
INCREMENTAL_OVERLAP_DAYS = 21
_NO_PURCHASE_RE = re.compile(
    r"From (\d{1,2} [A-Za-z]+ \d{4}) through (\d{1,2} [A-Za-z]+ \d{4}),"
    r".*?did not buy any shares",
    re.I,
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class BuybackStatus:
    program_reference_date: str
    period_start: str
    period_end: str
    period_shares: int
    period_avg_price_nok: Decimal
    period_amount_nok: Decimal
    cumulative_program_shares: int
    cumulative_program_avg_price_nok: Decimal
    cumulative_program_amount_nok: Decimal
    max_program_shares: int
    treasury_shares_after: int

    @property
    def program_external_id(self) -> str:
        return f"otec-buyback-{self.program_reference_date}"


def decimal_text(value: Decimal | str | int | float) -> str:
    return format(Decimal(str(value)), "f")


def _iso_date(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value.strip())
    if not match:
        raise ValueError(f"Ugyldig NewsWeb-buybackdato: {value}")
    day, month, year = match.groups()
    return datetime(int(year), _MONTHS[month.lower()], int(day)).date().isoformat()


def _integer(value: str) -> int:
    return int(value.replace(",", "").replace(" ", ""))


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "").strip())


def normalize_weekly_body(text: str) -> str:
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
    clean = re.sub(
        r"(average price of NOK\s+)(\d+),(\d{1,4})(?=\s)",
        lambda match: f"{match.group(1)}{match.group(2)}.{match.group(3)}",
        clean,
        flags=re.I,
    )
    return clean


def _parse_standard_status(clean: str) -> BuybackStatus:
    ref = re.search(
        r"notice from (\d{1,2} [A-Za-z]+ \d{4}) announcing the initiation of the share buyback program",
        clean,
        re.I,
    )
    period = re.search(
        r"From (\d{1,2} [A-Za-z]+ \d{4}) through (\d{1,2} [A-Za-z]+ \d{4}),"
        r".*?has bought ([\d,]+) shares .*?average price of NOK ([\d.,]+)"
        r" and a total value of NOK ([\d,]+)",
        clean,
        re.I,
    )
    cumulative = re.search(
        r"Since the initiation of this share buyback program a total of ([\d,]+) shares"
        r" at an average price of NOK ([\d.,]+) and a total value of NOK ([\d,]+) have been acquired",
        clean,
        re.I,
    )
    maximum = re.search(
        r"maximum number of shares that can be purchased under this buyback program is ([\d,]+)",
        clean,
        re.I,
    )
    treasury = re.search(
        r"At present date, Otello owns ([\d,]+) treasury shares",
        clean,
        re.I,
    )
    missing = [
        name
        for name, value in (
            ("program reference", ref),
            ("period", period),
            ("cumulative", cumulative),
            ("maximum", maximum),
            ("treasury shares", treasury),
        )
        if value is None
    ]
    if missing:
        raise ValueError("Kunne ikke parse buyback-melding; mangler: " + ", ".join(missing))
    return BuybackStatus(
        program_reference_date=_iso_date(ref.group(1)),
        period_start=_iso_date(period.group(1)),
        period_end=_iso_date(period.group(2)),
        period_shares=_integer(period.group(3)),
        period_avg_price_nok=_decimal(period.group(4)),
        period_amount_nok=_decimal(period.group(5)),
        cumulative_program_shares=_integer(cumulative.group(1)),
        cumulative_program_avg_price_nok=_decimal(cumulative.group(2)),
        cumulative_program_amount_nok=_decimal(cumulative.group(3)),
        max_program_shares=_integer(maximum.group(1)),
        treasury_shares_after=_integer(treasury.group(1)),
    )


def _parse_first_program_week(clean: str) -> BuybackStatus | None:
    ref = re.search(
        r"notice(?:s)? from (\d{1,2} [A-Za-z]+ \d{4}) announcing the initiation of the share buyback program",
        clean,
        re.I,
    )
    period = re.search(
        r"From (\d{1,2} [A-Za-z]+ \d{4}) through (\d{1,2} [A-Za-z]+ \d{4}),"
        r".*?has bought ([\d, ]+) shares .*?average price of NOK ([\d.,]+)"
        r" and a total value of NOK ([\d, ]+)",
        clean,
        re.I,
    )
    maximum = re.search(
        r"maximum number of shares that can be purchased under this buyback program is ([\d, ]+)",
        clean,
        re.I,
    )
    if not (ref and period and maximum):
        return None
    reference_date = _iso_date(ref.group(1))
    period_start = _iso_date(period.group(1))
    if reference_date != period_start:
        return None
    shares = _integer(period.group(3))
    avg_price = _decimal(period.group(4))
    amount = _decimal(period.group(5))
    if shares <= 0 or avg_price <= 0 or amount <= 0:
        return None
    return BuybackStatus(
        program_reference_date=reference_date,
        period_start=period_start,
        period_end=_iso_date(period.group(2)),
        period_shares=shares,
        period_avg_price_nok=avg_price,
        period_amount_nok=amount,
        cumulative_program_shares=shares,
        cumulative_program_avg_price_nok=avg_price,
        cumulative_program_amount_nok=amount,
        max_program_shares=_integer(maximum.group(1)),
        treasury_shares_after=shares,
    )


def parse_newsweb_weekly_status(text: str) -> BuybackStatus:
    clean = normalize_weekly_body(text)
    try:
        return _parse_standard_status(clean)
    except ValueError as standard_error:
        first_week = _parse_first_program_week(clean)
        if first_week is not None:
            return first_week
        raise standard_error


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
        "worker_ingestion": True,
        "attachment_processing": "DEFERRED_TO_FULL_REFRESH_R2",
    }


def _parsed_values(parsed: BuybackStatus) -> dict[str, Any]:
    return {
        "shares": parsed.period_shares,
        "avg_price_nok": decimal_text(parsed.period_avg_price_nok),
        "amount_nok": decimal_text(parsed.period_amount_nok),
        "cumulative_program_shares": parsed.cumulative_program_shares,
        "cumulative_program_avg_price_nok": decimal_text(parsed.cumulative_program_avg_price_nok),
        "cumulative_program_amount_nok": decimal_text(parsed.cumulative_program_amount_nok),
        "treasury_shares_after": parsed.treasury_shares_after,
    }


async def _source_priority(repository: D1WriteRepository, document_id: int | None) -> int:
    if document_id is None:
        return 99
    row = await repository.first(
        """
        SELECT s.code, s.is_official
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE sd.id=?
        LIMIT 1
        """,
        (document_id,),
    )
    if row is None:
        return 99
    if row.get("code") == "EURONEXT":
        return 0
    if int(row.get("is_official") or 0):
        return 1
    return 10


async def _preferred_document_id(
    repository: D1WriteRepository,
    existing_document_id: int | None,
    new_document_id: int,
) -> int:
    return (
        new_document_id
        if await _source_priority(repository, new_document_id)
        < await _source_priority(repository, existing_document_id)
        else (existing_document_id or new_document_id)
    )


def _assert_candidate_matches_existing(existing: dict[str, Any], parsed: BuybackStatus) -> None:
    candidate = _parsed_values(parsed)
    mismatches: list[str] = []
    for field, expected in candidate.items():
        actual = existing.get(field)
        if actual is None and expected is None:
            continue
        if str(actual) != str(expected):
            mismatches.append(f"{field}: lagret={actual}, kandidat={expected}")
    if mismatches:
        raise ValueError(
            "Buyback-kilde med lik/lavere prioritet avviker fra lagret sterkere fakta; "
            "krever kontroll: " + "; ".join(mismatches)
        )


async def _store_no_purchase_message(
    repository: D1WriteRepository,
    message: NewsWebMessage,
    period_text: str,
) -> int:
    return await repository.create_source_document(
        source_code="NEWSWEB",
        external_id=f"newsweb-message:{message.message_id}",
        document_type="REGULATORY_NEWS",
        title=message.title,
        url=message.public_url,
        published_at=message.published_at,
        content_sha256=hashlib.sha256(message.body.encode("utf-8")).hexdigest(),
        metadata={
            **_message_metadata(message),
            "buyback_status": "NO_PURCHASES",
            "period_text": period_text,
        },
    )


async def ingest_weekly_buyback(
    repository: D1WriteRepository,
    message: NewsWebMessage,
    parsed: BuybackStatus,
) -> dict[str, Any]:
    metadata = {"parser": "otec-buyback-status-v1", **_message_metadata(message)}
    document_id = await repository.create_source_document(
        source_code="NEWSWEB",
        external_id=message.public_url,
        document_type="REGULATORY_NEWS_MIRROR",
        title="Otello Corporation share buyback program status",
        url=message.public_url,
        published_at=message.published_at,
        content_sha256=hashlib.sha256(message.body.encode("utf-8")).hexdigest(),
        metadata=metadata,
    )

    program = await repository.first(
        "SELECT id, max_shares, source_document_id FROM buyback_programs WHERE external_program_id=? LIMIT 1",
        (parsed.program_external_id,),
    )
    if program is None:
        await repository.run(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, max_shares,
                status, source_document_id, notes
            ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                parsed.program_external_id,
                f"{parsed.program_reference_date}T00:00:00Z",
                parsed.program_reference_date,
                parsed.max_program_shares,
                document_id,
                "Program reconstructed from NEWSWEB mirror of Oslo Bors status; initiation document can supersede this source later.",
            ),
        )
        program = await repository.first(
            "SELECT id, max_shares, source_document_id FROM buyback_programs WHERE external_program_id=? LIMIT 1",
            (parsed.program_external_id,),
        )
        if program is None:
            raise RuntimeError("Buyback-program ble skrevet, men kunne ikke leses tilbake")
    else:
        old_priority = await _source_priority(repository, int(program["source_document_id"]))
        new_priority = await _source_priority(repository, document_id)
        same_document = int(program["source_document_id"]) == document_id
        if (
            not same_document
            and new_priority >= old_priority
            and int(program.get("max_shares") or 0) != parsed.max_program_shares
        ):
            raise ValueError(
                "Buyback-programdata fra lik/lavere prioritert kilde avviker fra lagret max_shares; krever kontroll"
            )
        if same_document or new_priority < old_priority:
            await repository.run(
                "UPDATE buyback_programs SET max_shares=?, source_document_id=? WHERE id=?",
                (parsed.max_program_shares, document_id, int(program["id"])),
            )

    program_id = int(program["id"])
    existing = await repository.first(
        """
        SELECT id, period_start, shares, avg_price_nok, amount_nok,
               cumulative_program_shares, cumulative_program_avg_price_nok,
               cumulative_program_amount_nok, treasury_shares_after, source_document_id
        FROM buybacks
        WHERE program_id=? AND trade_date=?
        ORDER BY id LIMIT 1
        """,
        (program_id, parsed.period_end),
    )
    source_applied = True
    if existing is None:
        await repository.run(
            """
            INSERT INTO buybacks(
                program_id, period_start, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, cumulative_program_avg_price_nok,
                cumulative_program_amount_nok, treasury_shares_after, source_document_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                program_id,
                parsed.period_start,
                parsed.period_end,
                parsed.period_shares,
                decimal_text(parsed.period_avg_price_nok),
                decimal_text(parsed.period_amount_nok),
                parsed.cumulative_program_shares,
                decimal_text(parsed.cumulative_program_avg_price_nok),
                decimal_text(parsed.cumulative_program_amount_nok),
                parsed.treasury_shares_after,
                document_id,
            ),
        )
        existing = await repository.first(
            """
            SELECT id, period_start, shares, avg_price_nok, amount_nok,
                   cumulative_program_shares, cumulative_program_avg_price_nok,
                   cumulative_program_amount_nok, treasury_shares_after, source_document_id
            FROM buybacks WHERE program_id=? AND trade_date=? ORDER BY id LIMIT 1
            """,
            (program_id, parsed.period_end),
        )
        if existing is None:
            raise RuntimeError("Buyback-rad ble skrevet, men kunne ikke leses tilbake")
        preferred_document_id = document_id
    else:
        buyback_id = int(existing["id"])
        existing_period_start = existing.get("period_start")
        if existing_period_start is not None and str(existing_period_start) != parsed.period_start:
            raise ValueError(
                "Buyback-kilde avviker fra lagret period_start; krever kontroll: "
                f"lagret={existing_period_start}, kandidat={parsed.period_start}"
            )
        if existing_period_start is None:
            await repository.run(
                "UPDATE buybacks SET period_start=? WHERE id=?",
                (parsed.period_start, buyback_id),
            )
        old_priority = await _source_priority(repository, int(existing["source_document_id"]))
        new_priority = await _source_priority(repository, document_id)
        same_document = int(existing["source_document_id"]) == document_id
        may_replace = same_document or new_priority < old_priority
        if not may_replace:
            _assert_candidate_matches_existing(existing, parsed)
            source_applied = False
            preferred_document_id = int(existing["source_document_id"])
        else:
            preferred_document_id = document_id
            await repository.run(
                """
                UPDATE buybacks SET period_start=?, shares=?, avg_price_nok=?, amount_nok=?,
                    cumulative_program_shares=?, cumulative_program_avg_price_nok=?,
                    cumulative_program_amount_nok=?, treasury_shares_after=?, source_document_id=?
                WHERE id=?
                """,
                (
                    parsed.period_start,
                    parsed.period_shares,
                    decimal_text(parsed.period_avg_price_nok),
                    decimal_text(parsed.period_amount_nok),
                    parsed.cumulative_program_shares,
                    decimal_text(parsed.cumulative_program_avg_price_nok),
                    decimal_text(parsed.cumulative_program_amount_nok),
                    parsed.treasury_shares_after,
                    preferred_document_id,
                    buyback_id,
                ),
            )

    buyback_id = int(existing["id"])
    cash_rows = await repository.all(
        """
        SELECT id, source_document_id FROM cash_movements
        WHERE movement_type='OTELLO_BUYBACK' AND movement_date=?
        ORDER BY id
        """,
        (parsed.period_end,),
    )
    cash_amount = decimal_text(-parsed.period_amount_nok)
    cash_description = (
        f"Otello buyback: {parsed.period_shares:,} shares during "
        f"{parsed.period_start}–{parsed.period_end}."
    )
    if not cash_rows:
        await repository.run(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, amount_original, currency,
                fx_rate_to_nok, description, source_document_id, confidence
            ) VALUES (?, 'OTELLO_BUYBACK', ?, ?, 'NOK', '1', ?, ?, 'CONFIRMED')
            """,
            (
                parsed.period_end,
                cash_amount,
                cash_amount,
                cash_description,
                preferred_document_id,
            ),
        )
    else:
        cash_document_id = await _preferred_document_id(
            repository,
            int(cash_rows[0]["source_document_id"]) if cash_rows[0].get("source_document_id") is not None else None,
            preferred_document_id,
        )
        await repository.run(
            """
            UPDATE cash_movements SET amount_nok=?, amount_original=?, description=?,
                source_document_id=?, confidence='CONFIRMED'
            WHERE id=?
            """,
            (cash_amount, cash_amount, cash_description, cash_document_id, int(cash_rows[0]["id"])),
        )
        for duplicate in cash_rows[1:]:
            await repository.run("DELETE FROM cash_movements WHERE id=?", (int(duplicate["id"]),))

    latest_total = await repository.first(
        """
        SELECT total_shares FROM otello_share_counts
        WHERE effective_from<=?
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (parsed.period_end,),
    )
    if latest_total is None:
        raise ValueError("Mangler registrert totalaksjetall før buyback-perioden")
    total_shares = int(latest_total["total_shares"])
    outstanding = total_shares - parsed.treasury_shares_after
    if outstanding <= 0:
        raise ValueError("Buyback-parser ga ugyldig antall utestående aksjer")

    share_rows = await repository.all(
        """
        SELECT id, source_document_id FROM otello_share_counts
        WHERE effective_from=? AND notes LIKE 'Treasury shares from weekly %'
        ORDER BY id
        """,
        (parsed.period_end,),
    )
    share_notes = (
        "Treasury shares from weekly NEWSWEB mirror of Oslo Bors status; "
        f"effective at period end {parsed.period_end}."
    )
    if not share_rows:
        await repository.run(
            """
            INSERT INTO otello_share_counts(
                effective_from, total_shares, treasury_shares, outstanding_shares,
                source_document_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.period_end,
                total_shares,
                parsed.treasury_shares_after,
                outstanding,
                preferred_document_id,
                share_notes,
            ),
        )
    else:
        share_document_id = await _preferred_document_id(
            repository,
            int(share_rows[0]["source_document_id"]),
            preferred_document_id,
        )
        source_label = (
            "Euronext status"
            if await _source_priority(repository, share_document_id) == 0
            else "NEWSWEB mirror of Oslo Bors status"
        )
        await repository.run(
            """
            UPDATE otello_share_counts SET total_shares=?, treasury_shares=?,
                outstanding_shares=?, source_document_id=?, notes=? WHERE id=?
            """,
            (
                total_shares,
                parsed.treasury_shares_after,
                outstanding,
                share_document_id,
                f"Treasury shares from weekly {source_label}; effective at period end {parsed.period_end}.",
                int(share_rows[0]["id"]),
            ),
        )
        for duplicate in share_rows[1:]:
            await repository.run("DELETE FROM otello_share_counts WHERE id=?", (int(duplicate["id"]),))

    duplicates = await repository.all(
        """
        SELECT id, source_document_id FROM buybacks
        WHERE program_id=? AND trade_date=? AND id<>?
        ORDER BY id
        """,
        (program_id, parsed.period_end, buyback_id),
    )
    for duplicate in duplicates:
        if await _source_priority(repository, int(duplicate["source_document_id"])) < await _source_priority(
            repository, preferred_document_id
        ):
            raise ValueError(
                "Fant eldre duplikat med sterkere provenance enn kanonisk buyback-rad; krever kontroll"
            )
        await repository.run("DELETE FROM buybacks WHERE id=?", (int(duplicate["id"]),))

    return {
        "buyback_id": buyback_id,
        "program_id": program_id,
        "period_start": parsed.period_start,
        "period_end": parsed.period_end,
        "period_shares": parsed.period_shares,
        "period_amount_nok": decimal_text(parsed.period_amount_nok),
        "cumulative_program_shares": parsed.cumulative_program_shares,
        "cumulative_program_avg_price_nok": decimal_text(parsed.cumulative_program_avg_price_nok),
        "cumulative_program_amount_nok": decimal_text(parsed.cumulative_program_amount_nok),
        "treasury_shares_after": parsed.treasury_shares_after,
        "outstanding_shares_after": outstanding,
        "source_code": "NEWSWEB",
        "source_applied": source_applied,
        "canonical_source_document_id": preferred_document_id,
        "attachment_status": "DEFERRED_TO_FULL_REFRESH_R2" if message.attachments else "NO_ATTACHMENT",
    }


async def buyback_start_for_refresh(repository: D1WriteRepository) -> str:
    # SQLite's reference anchors on daily transaction detail. The Worker fast path defers
    # PDF parsing, so use the latest of daily detail and weekly buyback facts, then retain
    # the same 21-day overlap. This prevents every 30-minute cycle from re-reading years.
    row = await repository.first(
        """
        SELECT MAX(d) AS latest_date FROM (
            SELECT MAX(trade_date) AS d FROM buyback_daily_transactions
            UNION ALL
            SELECT MAX(trade_date) AS d FROM buybacks
        )
        """
    )
    latest = str(row["latest_date"]) if row and row.get("latest_date") else None
    if not latest:
        return DEFAULT_BACKFILL_START
    overlap = date.fromisoformat(latest) - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
    return max(DEFAULT_BACKFILL_START, overlap.isoformat())


async def collect_newsweb_buybacks(
    repository: D1WriteRepository,
    *,
    to_date: str,
    from_date: str | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    start = from_date or await buyback_start_for_refresh(repository)
    discovered = await discover_otec_messages(
        start,
        to_date,
        message_title=BUYBACK_TITLE,
        fetcher=fetcher,
    )
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for item in discovered:
        try:
            message = await fetch_message(item.message_id, fetcher=fetcher)
            if BUYBACK_TITLE not in message.title.lower():
                raise ValueError(f"NewsWeb-melding {message.message_id} er ikke en buyback-status")
            clean = normalize_weekly_body(message.body)
            no_purchase = _NO_PURCHASE_RE.search(clean)
            if no_purchase:
                document_id = await _store_no_purchase_message(repository, message, no_purchase.group(0))
                results.append(
                    {
                        "message_id": message.message_id,
                        "canonical_source_document_id": document_id,
                        "daily_rows_written": 0,
                        "daily_rows": 0,
                        "daily_status": "NO_PURCHASES",
                        "attachment_status": "DEFERRED_TO_FULL_REFRESH_R2" if message.attachments else "NO_ATTACHMENT",
                    }
                )
                continue
            parsed = parse_newsweb_weekly_status(clean)
            results.append(await ingest_weekly_buyback(repository, message, parsed))
        except Exception as exc:
            errors.append(
                {
                    "message_id": item.message_id,
                    "published_at": item.published_at,
                    "title": item.title,
                    "error": str(exc)[:1000],
                }
            )
    return {
        "status": "error" if errors and not results else ("partial" if errors else "ok"),
        "source": "Oslo Børs NewsWeb",
        "issuer_id": 7759,
        "from": start,
        "to": to_date,
        "discovered": len(discovered),
        "ingested": len(results),
        "no_purchase_count": sum(item.get("daily_status") == "NO_PURCHASES" for item in results),
        "attachments_deferred": sum(
            item.get("attachment_status") == "DEFERRED_TO_FULL_REFRESH_R2" for item in results
        ),
        "results": results,
        "errors": errors,
    }
