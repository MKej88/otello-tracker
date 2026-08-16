from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, decimal_text

MAX_FX_LOOKBACK_DAYS = 7

EVENTS = (
    {
        "key": "adcolony_final_installment_2022_01_15",
        "movement_date": "2022-01-15",
        "movement_type": "OTHER",
        "amount_original": Decimal("191700000"),
        "currency": "USD",
        "source": {
            "code": "OTELLO_IR",
            "external_id": "otello-1h22",
            "document_type": "HALF_YEAR_REPORT",
            "title": "Otello Corporation ASA - 1H 2022",
            "published_at": "2022-08-17T00:00:00Z",
            "url": "https://otello.cdn.prismic.io/otello/52573fe3-21d9-4372-875f-39103e9fdee1_1H22.pdf",
        },
        "description": (
            "Final AdColony consideration received from Digital Turbine. The 1H22 report "
            "states USD 191.7m of discontinued-operation proceeds and confirms the final "
            "installment was received in cash. Modeled on the contractual 15 Jan 2022 "
            "settlement date and translated with the nearest prior ECB USD/NOK rate."
        ),
    },
    {
        "key": "bemobi_tax_settlement_2022_04_20",
        "movement_date": "2022-04-20",
        "movement_type": "TAX",
        "amount_original": Decimal("-67334818"),
        "currency": "BRL",
        "source": {
            "code": "OTELLO_IR",
            "external_id": "otello-bemobi-tax-settlement-2022-04-20",
            "document_type": "ISSUER_RELEASE",
            "title": "Settlement of tax for Bemobi",
            "published_at": "2022-04-20T00:00:00Z",
            "url": "https://news.cision.com/otello-corporation-asa/r/settlement-of-tax-for-bemobi,c3548563",
        },
        "description": (
            "Confirmed Bemobi-related Brazilian tax settlement: BRL 65,292,003 capital "
            "gains tax plus BRL 2,042,815 IOF, total BRL 67,334,818. Translated with the "
            "nearest prior ECB BRL/NOK rate."
        ),
    },
)


def _nearest_fx(connection, currency: str, movement_date: str):
    floor_date = (date.fromisoformat(movement_date) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT id, substr(observed_at, 1, 10) AS rate_date, rate
        FROM fx_rates
        WHERE base_currency = ? AND quote_currency = 'NOK'
          AND substr(observed_at, 1, 10) <= ?
          AND substr(observed_at, 1, 10) >= ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (currency, movement_date, floor_date),
    ).fetchone()


def seed_2022_cash_events(database_path: str | None = None) -> dict[str, Any]:
    """Seed the two major non-recurring H1 2022 cash events used by the cash curve.

    Values are stored in original currency and converted deterministically using the same
    ECB daily-rate convention as reported cash anchors. The function is idempotent: a
    matching event is updated in place rather than duplicated.
    """
    written = 0
    updated = 0
    missing_fx: list[dict[str, str]] = []
    rows: list[dict[str, str]] = []

    with get_connection(database_path) as connection:
        for event in EVENTS:
            source = event["source"]
            document_id = create_source_document(
                connection,
                source_code=source["code"],
                external_id=source["external_id"],
                document_type=source["document_type"],
                title=source["title"],
                published_at=source["published_at"],
                url=source["url"],
                metadata={
                    "cash_event_key": event["key"],
                    "source_quality": "CURATED_OFFICIAL",
                    "structured_transcription": True,
                },
            )

            fx = _nearest_fx(connection, event["currency"], event["movement_date"])
            if fx is None:
                missing_fx.append(
                    {
                        "key": event["key"],
                        "currency": event["currency"],
                        "movement_date": event["movement_date"],
                    }
                )
                continue

            original = Decimal(event["amount_original"])
            fx_rate = Decimal(fx["rate"])
            amount_nok = original * fx_rate
            existing = connection.execute(
                """
                SELECT id FROM cash_movements
                WHERE movement_date = ? AND movement_type = ? AND source_document_id = ?
                ORDER BY id LIMIT 1
                """,
                (event["movement_date"], event["movement_type"], document_id),
            ).fetchone()
            values = (
                decimal_text(amount_nok),
                decimal_text(original),
                event["currency"],
                decimal_text(fx_rate),
                event["description"],
                document_id,
            )
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO cash_movements(
                        movement_date, movement_type, amount_nok, amount_original,
                        currency, fx_rate_to_nok, description, source_document_id, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED')
                    """,
                    (event["movement_date"], event["movement_type"], *values),
                )
                movement_id = int(cursor.lastrowid)
                written += 1
            else:
                movement_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE cash_movements
                    SET amount_nok = ?, amount_original = ?, currency = ?, fx_rate_to_nok = ?,
                        description = ?, source_document_id = ?, confidence = 'CONFIRMED'
                    WHERE id = ?
                    """,
                    (*values, movement_id),
                )
                updated += 1

            rows.append(
                {
                    "key": event["key"],
                    "movement_date": event["movement_date"],
                    "movement_type": event["movement_type"],
                    "amount_original": decimal_text(original),
                    "currency": event["currency"],
                    "fx_rate_to_nok": decimal_text(fx_rate),
                    "fx_date": fx["rate_date"],
                    "amount_nok": decimal_text(amount_nok),
                    "movement_id": str(movement_id),
                }
            )

        connection.commit()

    return {
        "written": written,
        "updated": updated,
        "missing_fx": missing_fx,
        "events": rows,
    }
