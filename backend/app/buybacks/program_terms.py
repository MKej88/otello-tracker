from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, decimal_text
from app.newsweb.client import discover_otec_messages, fetch_message

BUYBACK_TITLE = "share buyback program status"
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _iso_date(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value.strip())
    if not match:
        raise ValueError(f"Invalid Otello program reference date: {value}")
    day, month, year = match.groups()
    return datetime(int(year), _MONTHS[month.lower()], int(day)).date().isoformat()


def parse_program_terms(text: str) -> dict[str, Any]:
    clean = " ".join(text.split())
    reference = re.search(
        r"(?:notice|stock exchange notice) from (\d{1,2} [A-Za-z]+ \d{4}) announcing the initiation of the share buyback program",
        clean,
        re.I,
    )
    max_price = re.search(
        r"maximum consideration to be paid for shares acquired under this buyback program is NOK ([\d.,]+) per share",
        clean,
        re.I,
    )
    max_shares = re.search(
        r"maximum number of shares that can be purchased under this buyback program is ([\d, ]+)",
        clean,
        re.I,
    )
    missing = [
        name for name, match in (
            ("program reference", reference),
            ("maximum consideration", max_price),
            ("maximum shares", max_shares),
        ) if match is None
    ]
    if missing:
        raise ValueError("Could not parse buyback program terms: " + ", ".join(missing))
    return {
        "program_reference_date": _iso_date(reference.group(1)),
        "max_price_nok": Decimal(max_price.group(1).replace(",", "")),
        "max_shares": int(max_shares.group(1).replace(",", "").replace(" ", "")),
    }


def sync_current_program_terms(
    database_path: str | None = None,
    *,
    to_date: str | None = None,
    lookback_days: int = 120,
    timeout: int = 30,
) -> dict[str, Any]:
    end = date.fromisoformat(to_date) if to_date else date.today()
    start = end - timedelta(days=max(30, lookback_days))
    discovered = discover_otec_messages(
        start.isoformat(), end.isoformat(), message_title=BUYBACK_TITLE, timeout=timeout
    )
    if not discovered:
        return {"status": "not_ready", "reason": "no recent buyback status message"}

    latest = discovered[-1]
    message = fetch_message(latest.message_id, timeout=timeout)
    terms = parse_program_terms(message.body)
    external_program_id = f"otec-buyback-{terms['program_reference_date']}"

    with get_connection(database_path) as connection:
        program = connection.execute(
            "SELECT id, max_shares FROM buyback_programs WHERE external_program_id=?",
            (external_program_id,),
        ).fetchone()
        if program is None:
            return {
                "status": "not_ready",
                "reason": "latest program has not been ingested yet",
                "external_program_id": external_program_id,
            }
        if int(program["max_shares"] or 0) != int(terms["max_shares"]):
            raise ValueError(
                f"Program max_shares mismatch: database={program['max_shares']} message={terms['max_shares']}"
            )

        document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id=f"newsweb-message:{message.message_id}",
            document_type="REGULATORY_NEWS",
            title=message.title,
            url=message.public_url,
            published_at=message.published_at,
            content_sha256=hashlib.sha256(message.body.encode("utf-8")).hexdigest(),
            metadata={
                "buyback_program_terms_parsed": True,
                "max_price_nok": decimal_text(terms["max_price_nok"]),
                "max_shares": terms["max_shares"],
                "program_reference_date": terms["program_reference_date"],
            },
        )
        connection.execute(
            "UPDATE buyback_programs SET max_price_nok=? WHERE id=?",
            (decimal_text(terms["max_price_nok"]), int(program["id"])),
        )
        exists = connection.execute(
            """
            SELECT 1 FROM provenance_records
            WHERE entity_table='buyback_programs' AND entity_id=?
              AND field_name='max_price_nok' AND source_document_id=?
            LIMIT 1
            """,
            (int(program["id"]), document_id),
        ).fetchone()
        if exists is None:
            connection.execute(
                """
                INSERT INTO provenance_records(
                    entity_table, entity_id, field_name, source_document_id,
                    source_locator, extraction_method, confidence, extracted_value
                ) VALUES ('buyback_programs', ?, 'max_price_nok', ?, ?, 'PARSER', 'HIGH', ?)
                """,
                (
                    int(program["id"]), document_id,
                    "Maximum consideration sentence in weekly NewsWeb status",
                    decimal_text(terms["max_price_nok"]),
                ),
            )
        connection.commit()

    return {
        "status": "ok",
        "message_id": message.message_id,
        "program_reference_date": terms["program_reference_date"],
        "max_price_nok": decimal_text(terms["max_price_nok"]),
        "max_shares": terms["max_shares"],
    }
