from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, decimal_text

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _date(text: str) -> str:
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text.strip())
    if not match:
        raise ValueError(f"Ugyldig dato i buyback-melding: {text}")
    day, month, year = match.groups()
    return datetime(int(year), _MONTHS[month.lower()], int(day)).date().isoformat()


def _int(text: str) -> int:
    return int(text.replace(",", "").replace(" ", ""))


def _dec(text: str) -> Decimal:
    return Decimal(text.replace(",", "").strip())


def _source_priority(connection, document_id: int | None) -> int:
    """Lower is better; a direct/curated Euronext fact always beats a mirror."""
    if document_id is None:
        return 99
    row = connection.execute(
        """
        SELECT s.code, s.is_official
        FROM source_documents sd
        JOIN sources s ON s.id = sd.source_id
        WHERE sd.id = ?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        return 99
    if row["code"] == "EURONEXT":
        return 0
    if row["is_official"]:
        return 1
    return 10


def _preferred_document_id(connection, existing_document_id: int | None, new_document_id: int) -> int:
    return (
        new_document_id
        if _source_priority(connection, new_document_id) < _source_priority(connection, existing_document_id)
        else (existing_document_id or new_document_id)
    )


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


def _assert_candidate_matches_existing(existing, parsed: BuybackStatus) -> None:
    candidate = _parsed_values(parsed)
    mismatches: list[str] = []
    for field, expected in candidate.items():
        actual = existing[field]
        if actual is None and expected is None:
            continue
        if str(actual) != str(expected):
            mismatches.append(f"{field}: lagret={actual}, kandidat={expected}")
    if mismatches:
        raise ValueError(
            "Buyback-kilde med lik/lavere prioritet avviker fra lagret sterkere fakta; "
            "krever kontroll: " + "; ".join(mismatches)
        )


def parse_euronext_buyback_status(text: str) -> BuybackStatus:
    """Parse Otello's standard weekly buyback-status announcement.

    This is deliberately deterministic and only accepts the published sentence pattern.
    If Otello changes wording, parsing fails loudly rather than guessing financial fields.
    """
    clean = " ".join(text.split())

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
        name for name, value in (
            ("program reference", ref), ("period", period), ("cumulative", cumulative),
            ("maximum", maximum), ("treasury shares", treasury),
        ) if value is None
    ]
    if missing:
        raise ValueError("Kunne ikke parse buyback-melding; mangler: " + ", ".join(missing))

    return BuybackStatus(
        program_reference_date=_date(ref.group(1)),
        period_start=_date(period.group(1)),
        period_end=_date(period.group(2)),
        period_shares=_int(period.group(3)),
        period_avg_price_nok=_dec(period.group(4)),
        period_amount_nok=_dec(period.group(5)),
        cumulative_program_shares=_int(cumulative.group(1)),
        cumulative_program_avg_price_nok=_dec(cumulative.group(2)),
        cumulative_program_amount_nok=_dec(cumulative.group(3)),
        max_program_shares=_int(maximum.group(1)),
        treasury_shares_after=_int(treasury.group(1)),
    )


def ingest_buyback_status(
    *,
    parsed: BuybackStatus,
    url: str,
    published_at: str,
    database_path: str | None = None,
    source_code: str = "EURONEXT",
    source_metadata: dict[str, Any] | None = None,
    content_hash: str | None = None,
) -> dict:
    """Persist one logical buyback period, never letting weaker evidence rewrite stronger facts."""
    metadata = {"parser": "otec-buyback-status-v1", **(source_metadata or {})}
    if source_code == "EURONEXT":
        document_type = "REGULATORY_NEWS"
        document_title = "Otello Corporation share buyback program status"
        source_label = "Euronext status"
    elif source_code == "OTELLO_IR":
        document_type = "ISSUER_RELEASE"
        document_title = "Otello Corporation issuer buyback release"
        source_label = "Otello issuer release"
    else:
        document_type = "REGULATORY_NEWS_MIRROR"
        document_title = "Otello Corporation share buyback program status"
        source_label = f"{source_code} mirror of Oslo Bors status"

    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code=source_code,
            external_id=url,
            document_type=document_type,
            title=document_title,
            url=url,
            published_at=published_at,
            content_sha256=content_hash,
            metadata=metadata,
        )

        program = connection.execute(
            "SELECT id, max_shares, source_document_id FROM buyback_programs WHERE external_program_id = ?",
            (parsed.program_external_id,),
        ).fetchone()
        if program is None:
            cursor = connection.execute(
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
                    f"Program reconstructed from {source_label}; initiation document can supersede this source later.",
                ),
            )
            program_id = int(cursor.lastrowid)
        else:
            program_id = int(program["id"])
            old_priority = _source_priority(connection, program["source_document_id"])
            new_priority = _source_priority(connection, document_id)
            same_document = int(program["source_document_id"]) == document_id
            if not same_document and new_priority >= old_priority and int(program["max_shares"] or 0) != parsed.max_program_shares:
                raise ValueError(
                    "Buyback-programdata fra lik/lavere prioritert kilde avviker fra lagret max_shares; krever kontroll"
                )
            if same_document or new_priority < old_priority:
                connection.execute(
                    "UPDATE buyback_programs SET max_shares = ?, source_document_id = ? WHERE id = ?",
                    (parsed.max_program_shares, document_id, program_id),
                )

        existing = connection.execute(
            """
            SELECT id, shares, avg_price_nok, amount_nok,
                   cumulative_program_shares, cumulative_program_avg_price_nok,
                   cumulative_program_amount_nok, treasury_shares_after, source_document_id
            FROM buybacks
            WHERE program_id = ? AND trade_date = ?
            ORDER BY id LIMIT 1
            """,
            (program_id, parsed.period_end),
        ).fetchone()
        source_applied = True
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO buybacks(
                    program_id, trade_date, shares, avg_price_nok, amount_nok,
                    cumulative_program_shares, cumulative_program_avg_price_nok,
                    cumulative_program_amount_nok, treasury_shares_after, source_document_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    program_id, parsed.period_end, parsed.period_shares,
                    decimal_text(parsed.period_avg_price_nok), decimal_text(parsed.period_amount_nok),
                    parsed.cumulative_program_shares,
                    decimal_text(parsed.cumulative_program_avg_price_nok),
                    decimal_text(parsed.cumulative_program_amount_nok),
                    parsed.treasury_shares_after, document_id,
                ),
            )
            buyback_id = int(cursor.lastrowid)
            preferred_document_id = document_id
        else:
            buyback_id = int(existing["id"])
            old_priority = _source_priority(connection, existing["source_document_id"])
            new_priority = _source_priority(connection, document_id)
            same_document = int(existing["source_document_id"]) == document_id
            may_replace = same_document or new_priority < old_priority
            if not may_replace:
                _assert_candidate_matches_existing(existing, parsed)
                source_applied = False
                preferred_document_id = int(existing["source_document_id"])
            else:
                preferred_document_id = document_id
                connection.execute(
                    """
                    UPDATE buybacks SET shares = ?, avg_price_nok = ?, amount_nok = ?,
                        cumulative_program_shares = ?, cumulative_program_avg_price_nok = ?,
                        cumulative_program_amount_nok = ?, treasury_shares_after = ?,
                        source_document_id = ?
                    WHERE id = ?
                    """,
                    (
                        parsed.period_shares, decimal_text(parsed.period_avg_price_nok),
                        decimal_text(parsed.period_amount_nok), parsed.cumulative_program_shares,
                        decimal_text(parsed.cumulative_program_avg_price_nok),
                        decimal_text(parsed.cumulative_program_amount_nok), parsed.treasury_shares_after,
                        preferred_document_id, buyback_id,
                    ),
                )

        cash_rows = connection.execute(
            """
            SELECT id, source_document_id FROM cash_movements
            WHERE movement_type = 'OTELLO_BUYBACK' AND movement_date = ?
            ORDER BY id
            """,
            (parsed.period_end,),
        ).fetchall()
        cash_values = (
            decimal_text(-parsed.period_amount_nok),
            decimal_text(-parsed.period_amount_nok),
            f"Otello buyback: {parsed.period_shares:,} shares during {parsed.period_start}–{parsed.period_end}.",
        )
        if not cash_rows:
            connection.execute(
                """
                INSERT INTO cash_movements(
                    movement_date, movement_type, amount_nok, amount_original, currency,
                    fx_rate_to_nok, description, source_document_id, confidence
                ) VALUES (?, 'OTELLO_BUYBACK', ?, ?, 'NOK', '1', ?, ?, 'CONFIRMED')
                """,
                (parsed.period_end, *cash_values, preferred_document_id),
            )
        else:
            cash = cash_rows[0]
            cash_document_id = _preferred_document_id(connection, cash["source_document_id"], preferred_document_id)
            connection.execute(
                """
                UPDATE cash_movements SET amount_nok = ?, amount_original = ?, description = ?,
                    source_document_id = ?, confidence = 'CONFIRMED'
                WHERE id = ?
                """,
                (*cash_values, cash_document_id, cash["id"]),
            )
            for duplicate in cash_rows[1:]:
                connection.execute("DELETE FROM cash_movements WHERE id = ?", (duplicate["id"],))

        latest_total = connection.execute(
            """
            SELECT total_shares FROM otello_share_counts
            WHERE effective_from <= ? ORDER BY effective_from DESC, id DESC LIMIT 1
            """,
            (parsed.period_end,),
        ).fetchone()
        if latest_total is None:
            raise ValueError("Mangler registrert totalaksjetall før buyback-perioden")
        total_shares = int(latest_total["total_shares"])
        outstanding = total_shares - parsed.treasury_shares_after
        if outstanding <= 0:
            raise ValueError("Buyback-parser ga ugyldig antall utestående aksjer")

        share_rows = connection.execute(
            """
            SELECT id, source_document_id FROM otello_share_counts
            WHERE effective_from = ? AND notes LIKE 'Treasury shares from weekly %'
            ORDER BY id
            """,
            (parsed.period_end,),
        ).fetchall()
        share_notes = f"Treasury shares from weekly {source_label}; effective at period end {parsed.period_end}."
        if not share_rows:
            connection.execute(
                """
                INSERT INTO otello_share_counts(
                    effective_from, total_shares, treasury_shares, outstanding_shares,
                    source_document_id, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    parsed.period_end, total_shares, parsed.treasury_shares_after,
                    outstanding, preferred_document_id, share_notes,
                ),
            )
        else:
            share = share_rows[0]
            share_document_id = _preferred_document_id(connection, share["source_document_id"], preferred_document_id)
            share_source_label = (
                "Euronext status"
                if _source_priority(connection, share_document_id) == 0
                else source_label
            )
            connection.execute(
                """
                UPDATE otello_share_counts SET total_shares = ?, treasury_shares = ?,
                    outstanding_shares = ?, source_document_id = ?, notes = ? WHERE id = ?
                """,
                (
                    total_shares, parsed.treasury_shares_after, outstanding,
                    share_document_id,
                    f"Treasury shares from weekly {share_source_label}; effective at period end {parsed.period_end}.",
                    share["id"],
                ),
            )
            for duplicate in share_rows[1:]:
                connection.execute("DELETE FROM otello_share_counts WHERE id = ?", (duplicate["id"],))

        duplicates = connection.execute(
            """
            SELECT id, source_document_id FROM buybacks
            WHERE program_id = ? AND trade_date = ? AND id <> ?
            ORDER BY id
            """,
            (program_id, parsed.period_end, buyback_id),
        ).fetchall()
        for duplicate in duplicates:
            if _source_priority(connection, duplicate["source_document_id"]) < _source_priority(connection, preferred_document_id):
                raise ValueError(
                    "Fant eldre duplikat med sterkere provenance enn kanonisk buyback-rad; krever kontroll"
                )
            connection.execute("DELETE FROM buybacks WHERE id = ?", (duplicate["id"],))

        connection.commit()

    return {
        "buyback_id": buyback_id,
        "program_id": program_id,
        "period_end": parsed.period_end,
        "period_shares": parsed.period_shares,
        "period_amount_nok": decimal_text(parsed.period_amount_nok),
        "cumulative_program_shares": parsed.cumulative_program_shares,
        "cumulative_program_avg_price_nok": decimal_text(parsed.cumulative_program_avg_price_nok),
        "cumulative_program_amount_nok": decimal_text(parsed.cumulative_program_amount_nok),
        "treasury_shares_after": parsed.treasury_shares_after,
        "outstanding_shares_after": outstanding,
        "source_code": source_code,
        "source_applied": source_applied,
        "canonical_source_document_id": preferred_document_id,
    }


def ingest_euronext_buyback_status(
    *,
    text: str,
    url: str,
    published_at: str,
    database_path: str | None = None,
    source_code: str = "EURONEXT",
    source_metadata: dict[str, Any] | None = None,
) -> dict:
    parsed = parse_euronext_buyback_status(text)
    return ingest_buyback_status(
        parsed=parsed,
        url=url,
        published_at=published_at,
        database_path=database_path,
        source_code=source_code,
        source_metadata=source_metadata,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
