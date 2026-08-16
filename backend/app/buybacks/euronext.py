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


def ingest_euronext_buyback_status(
    *,
    text: str,
    url: str,
    published_at: str,
    database_path: str | None = None,
    source_code: str = "EURONEXT",
    source_metadata: dict[str, Any] | None = None,
) -> dict:
    """Ingest a strictly parsed status while preserving the actual fetched source.

    `source_code` defaults to EURONEXT for direct originals. A verified public mirror can
    be passed explicitly (for example MFN), but must keep upstream/canonical metadata so
    the database never mislabels mirrored bytes as an official-source fetch.
    """
    parsed = parse_euronext_buyback_status(text)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    metadata = {"parser": "otec-buyback-status-v1", **(source_metadata or {})}

    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code=source_code,
            external_id=url,
            document_type="REGULATORY_NEWS_MIRROR" if source_code != "EURONEXT" else "REGULATORY_NEWS",
            title="Otello Corporation share buyback program status",
            url=url,
            published_at=published_at,
            content_sha256=content_hash,
            metadata=metadata,
        )

        program = connection.execute(
            "SELECT id FROM buyback_programs WHERE external_program_id = ?",
            (parsed.program_external_id,),
        ).fetchone()
        source_label = "Euronext status" if source_code == "EURONEXT" else f"{source_code} mirror of Oslo Bors status"
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
                    f"Program reconstructed from weekly {source_label}; initiation document can supersede this source later.",
                ),
            )
            program_id = int(cursor.lastrowid)
        else:
            program_id = int(program["id"])
            connection.execute(
                "UPDATE buyback_programs SET max_shares = ? WHERE id = ?",
                (parsed.max_program_shares, program_id),
            )

        existing = connection.execute(
            "SELECT id FROM buybacks WHERE trade_date = ? AND source_document_id = ?",
            (parsed.period_end, document_id),
        ).fetchone()
        buyback_values = (
            program_id,
            parsed.period_shares,
            decimal_text(parsed.period_avg_price_nok),
            decimal_text(parsed.period_amount_nok),
            parsed.cumulative_program_shares,
            decimal_text(parsed.cumulative_program_avg_price_nok),
            decimal_text(parsed.cumulative_program_amount_nok),
            parsed.treasury_shares_after,
        )
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
        else:
            buyback_id = int(existing["id"])
            connection.execute(
                """
                UPDATE buybacks SET program_id = ?, shares = ?, avg_price_nok = ?, amount_nok = ?,
                    cumulative_program_shares = ?, cumulative_program_avg_price_nok = ?,
                    cumulative_program_amount_nok = ?, treasury_shares_after = ? WHERE id = ?
                """,
                (*buyback_values, buyback_id),
            )

        cash = connection.execute(
            """
            SELECT id FROM cash_movements
            WHERE movement_type = 'OTELLO_BUYBACK' AND movement_date = ? AND source_document_id = ?
            """,
            (parsed.period_end, document_id),
        ).fetchone()
        cash_values = (
            decimal_text(-parsed.period_amount_nok),
            decimal_text(-parsed.period_amount_nok),
            f"Weekly Otello buyback: {parsed.period_shares:,} shares during {parsed.period_start}–{parsed.period_end}.",
        )
        if cash is None:
            connection.execute(
                """
                INSERT INTO cash_movements(
                    movement_date, movement_type, amount_nok, amount_original, currency,
                    fx_rate_to_nok, description, source_document_id, confidence
                ) VALUES (?, 'OTELLO_BUYBACK', ?, ?, 'NOK', '1', ?, ?, 'CONFIRMED')
                """,
                (parsed.period_end, *cash_values, document_id),
            )
        else:
            connection.execute(
                """
                UPDATE cash_movements SET amount_nok = ?, amount_original = ?, description = ?
                WHERE id = ?
                """,
                (*cash_values, cash["id"]),
            )

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

        share_row = connection.execute(
            """
            SELECT id FROM otello_share_counts
            WHERE effective_from = ? AND source_document_id = ? LIMIT 1
            """,
            (parsed.period_end, document_id),
        ).fetchone()
        share_values = (
            total_shares, parsed.treasury_shares_after, outstanding,
            f"Treasury shares from weekly {source_label}; effective at period end {parsed.period_end}.",
        )
        if share_row is None:
            connection.execute(
                """
                INSERT INTO otello_share_counts(
                    effective_from, total_shares, treasury_shares, outstanding_shares,
                    source_document_id, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (parsed.period_end, *share_values[:3], document_id, share_values[3]),
            )
        else:
            connection.execute(
                """
                UPDATE otello_share_counts SET total_shares = ?, treasury_shares = ?,
                    outstanding_shares = ?, notes = ? WHERE id = ?
                """,
                (*share_values, share_row["id"]),
            )

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
    }
