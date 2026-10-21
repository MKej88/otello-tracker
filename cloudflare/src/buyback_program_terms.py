"""Official NewsWeb amendments to Otello's active share buyback price cap.

Only explicit, positive NOK-per-share ceilings in an announced buyback amendment
can change the live cap. Immutable source-document identities and effective dates
retain an audit trail; late historical status messages cannot reverse a change.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from newsweb_client import NewsWebMessage

_UPDATE_TITLE = re.compile(
    r"\b(?:share\s+)?buy[\s-]?back\s+program(?:me)?\b.{0,45}"
    r"\b(?:update|amend(?:ment|ed)?|revis(?:ion|ed)|increase|change)\b",
    re.I,
)
_CAP_CONTEXT = re.compile(
    r"\b(?:maximum\s+(?:consideration|purchase\s+price|price|amount)"
    r"|(?:price|consideration)\s+(?:cap|ceiling|limit)"
    r"|(?:upper|maximum)\s+price\s+limit)\b",
    re.I,
)
_NOK_AMOUNT = re.compile(r"\bNOK\s+(\d{1,4}(?:[.,]\d{1,2})?)\b", re.I)
_PROGRAM_NOTICE = re.compile(
    r"\b(?:notice|announcement)\s+(?:from|dated)\s+"
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
    re.I,
)
_MONTHS = {
    name.lower(): index
    for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"), 1
    )
}


def is_program_update_title(title: str) -> bool:
    return bool(_UPDATE_TITLE.search(" ".join(title.split())))


def parse_amended_price_cap(body: str) -> Decimal:
    """Require 'maximum/price cap' and NOK per share in the same sentence.

    A 'from NOK 20 to NOK 30 per share' announcement yields NOK 30, never 20.
    Ambiguous or absent caps must be flagged, not guessed from unrelated amounts.
    """
    clean = " ".join(body.split())
    for match in _CAP_CONTEXT.finditer(clean):
        sentence = clean[match.start():][:350]
        # Decimal dots inside NOK 20.00 must not terminate this context.
        sentence = re.split(r"(?<!\d)\.(?!\d)\s+|;\s+", sentence, maxsplit=1)[0]
        prices = list(_NOK_AMOUNT.finditer(sentence))
        if not prices or "per share" not in sentence.lower():
            continue
        last = prices[-1]
        try:
            amount = Decimal(last.group(1).replace(",", "."))
        except InvalidOperation:
            continue
        if amount > 0:
            return amount
    raise ValueError(
        "Endringsmelding for tilbakekjøp mangler entydig maksimal NOK-kurs per aksje; krever kontroll"
    )


def _reference_date(body: str) -> str | None:
    match = _PROGRAM_NOTICE.search(" ".join(body.split()))
    if not match:
        return None
    day, month, year = match.group(1).split()
    month_number = _MONTHS.get(month.lower())
    if month_number is None:
        return None
    return date(int(year), month_number, int(day)).isoformat()


async def record_program_price_cap(
    repository: Any,
    *,
    program: dict[str, Any],
    source_document_id: int,
    max_price_nok: Decimal,
    effective_at: str,
    event_kind: str,
) -> dict[str, Any]:
    """Append source-backed cap version and materialize only the newest cap.

    Bootstrap the pre-amendment ceiling with the program's existing original
    source so the historical forecast remains point-in-time accurate.
    """
    program_id = int(program["id"])
    old_price = program.get("max_price_nok")
    old_source_id = program.get("source_document_id")
    existing_cap = await repository.first(
        "SELECT id FROM buyback_program_cap_history WHERE program_id=? LIMIT 1",
        (program_id,),
    )
    if (
        existing_cap is None
        and old_price is not None
        and old_source_id is not None
        and int(old_source_id) != source_document_id
    ):
        baseline_date = str(program.get("start_date") or effective_at[:10])
        await repository.run(
            """
            INSERT OR IGNORE INTO buyback_program_cap_history(
                program_id, effective_at, max_price_nok, source_document_id, event_kind
            ) VALUES (?, ?, ?, ?, 'BASELINE')
            """,
            (program_id, f"{baseline_date}T00:00:00Z", str(old_price), int(old_source_id)),
        )
    await repository.run(
        """
        INSERT INTO buyback_program_cap_history(
            program_id, effective_at, max_price_nok, source_document_id, event_kind
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(program_id, source_document_id) DO UPDATE SET
            effective_at=excluded.effective_at,
            max_price_nok=excluded.max_price_nok,
            event_kind=excluded.event_kind
        """,
        (program_id, effective_at, format(max_price_nok, "f"), source_document_id, event_kind),
    )
    latest = await repository.first(
        """
        SELECT effective_at, max_price_nok, source_document_id
        FROM buyback_program_cap_history
        WHERE program_id=?
        ORDER BY effective_at DESC, id DESC LIMIT 1
        """,
        (program_id,),
    )
    if latest is None:
        raise RuntimeError("Lagret kursgrense kunne ikke leses tilbake")
    await repository.run(
        "UPDATE buyback_programs SET max_price_nok=? WHERE id=?",
        (str(latest["max_price_nok"]), program_id),
    )
    return {
        "program_id": program_id,
        "previous_price_cap_nok": str(old_price) if old_price is not None else None,
        "new_price_cap_nok": str(latest["max_price_nok"]),
        "effective_at": str(latest["effective_at"]),
        "applied_as_latest": int(latest["source_document_id"]) == source_document_id,
    }


async def ingest_program_cap_amendment(repository: Any, message: NewsWebMessage) -> dict[str, Any]:
    if not is_program_update_title(message.title):
        raise ValueError("NewsWeb-meldingen er ikke en endring av tilbakekjøpsprogrammet")
    new_cap = parse_amended_price_cap(message.body)
    published_date = str(message.published_at)[:10]
    reference = _reference_date(message.body)
    program = None
    if reference:
        program = await repository.first(
            """
            SELECT id, start_date, max_price_nok, source_document_id
            FROM buyback_programs
            WHERE external_program_id=? AND status='ACTIVE' LIMIT 1
            """,
            (f"otec-buyback-{reference}",),
        )
    if program is None:
        program = await repository.first(
            """
            SELECT id, start_date, max_price_nok, source_document_id
            FROM buyback_programs
            WHERE status='ACTIVE' AND start_date<=?
            ORDER BY start_date DESC, id DESC LIMIT 1
            """,
            (published_date,),
        )
    if program is None:
        raise ValueError("Ingen aktivt tilbakekjøpsprogram samsvarer med endringsmeldingen")

    import hashlib
    document_id = await repository.create_source_document(
        source_code="NEWSWEB",
        external_id=message.public_url,
        document_type="REGULATORY_NEWS",
        title=message.title,
        url=message.public_url,
        published_at=message.published_at,
        content_sha256=hashlib.sha256(message.body.encode("utf-8")).hexdigest(),
        metadata={
            "buyback_program_cap_amendment": True,
            "max_price_nok": format(new_cap, "f"),
            "newsweb_message_id": message.message_id,
            "reference_program_date": reference,
        },
    )
    outcome = await record_program_price_cap(
        repository,
        program=program,
        source_document_id=int(document_id),
        max_price_nok=new_cap,
        effective_at=str(message.published_at),
        event_kind="AMENDMENT",
    )
    return {
        **outcome,
        "message_id": message.message_id,
        "source_document_id": document_id,
        "program_cap_update": True,
    }
