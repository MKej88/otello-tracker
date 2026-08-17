from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, decimal_text

MAX_FX_LOOKBACK_DAYS = 7

TENDER_BUYBACKS = (
    {
        "key": "2021-05-10-tender",
        "message_id": 532327,
        "published_at": "2021-05-10T05:30:00Z",
        "title": "Completion of share buyback offer",
        "program_start": "2021-05-05",
        "trade_date": "2021-05-10",
        "shares": 12_000_000,
        "price_nok": Decimal("33.75"),
        "treasury_after": 13_727_702,
    },
    {
        "key": "2021-09-06-tender",
        "message_id": 541639,
        "published_at": "2021-09-06T05:30:15.226Z",
        "title": "Completion of share buy back offer",
        "program_start": "2021-08-30",
        "trade_date": "2021-09-06",
        "shares": 12_450_000,
        "price_nok": Decimal("33.00"),
        "treasury_after": 12_450_000,
    },
    {
        "key": "2021-12-08-tender",
        "message_id": 548716,
        "published_at": "2021-12-08T07:00:15.951Z",
        "title": "Completion of buy-back of own shares",
        "program_start": "2021-12-01",
        "trade_date": "2021-12-08",
        "shares": 11_200_000,
        "price_nok": Decimal("26.50"),
        "treasury_after": 11_200_000,
    },
)

SHARE_COUNT_EVENTS = (
    {
        "effective_from": "2021-09-06",
        "total_shares": 124_749_727,
        "treasury_shares": 12_450_000,
        "message_id": 541639,
        "title": "Completion of share buy back offer",
        "published_at": "2021-09-06T05:30:15.226Z",
        "notes": (
            "NewsWeb completion notice says Otello bought 12,450,000 shares and following "
            "the transaction owned 12,450,000 treasury shares. Registered total remained "
            "124,749,727 until the later capital-reduction registration."
        ),
    },
    {
        "effective_from": "2021-11-24",
        "total_shares": 112_299_727,
        "treasury_shares": 0,
        "message_id": 547678,
        "title": "Registration of share capital reduction",
        "published_at": "2021-11-24T07:30:14.029Z",
        "notes": (
            "NewsWeb confirms registration of the cancellation of the 12,450,000 tender "
            "shares and a new registered total of 112,299,727. The cancelled treasury "
            "balance is therefore reset to zero at registration."
        ),
    },
    {
        "effective_from": "2021-12-08",
        "total_shares": 112_299_727,
        "treasury_shares": 11_200_000,
        "message_id": 548716,
        "title": "Completion of buy-back of own shares",
        "published_at": "2021-12-08T07:00:15.951Z",
        "notes": (
            "NewsWeb completion notice says Otello bought 11,200,000 shares and following "
            "the transaction owned 11,200,000 treasury shares. The 31 Dec report anchor "
            "later supersedes this event-date estimate with the reported 11,199,998 balance."
        ),
    },
)

ADCOLONY_PAYMENT = {
    "movement_date": "2021-10-27",
    "message_id": 545173,
    "published_at": "2021-10-27T07:14:08.820Z",
    "title": "AdColony payment",
    "amount_original": Decimal("100000000"),
    "currency": "USD",
}


def _newsweb_document(
    connection,
    *,
    message_id: int,
    title: str,
    published_at: str,
    event_key: str,
) -> int:
    return create_source_document(
        connection,
        source_code="NEWSWEB",
        external_id=f"newsweb-message:{message_id}",
        document_type="REGULATORY_NEWS",
        title=title,
        url=f"https://newsweb.oslobors.no/message/{message_id}",
        published_at=published_at,
        metadata={
            "source_quality": "OFFICIAL_ORIGINAL",
            "structured_event_key": event_key,
            "structured_transcription": True,
            "newsweb_message_id": message_id,
        },
    )


def _nearest_fx(connection, currency: str, movement_date: str):
    floor = (date.fromisoformat(movement_date) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT id, substr(observed_at,1,10) rate_date, rate
        FROM fx_rates
        WHERE base_currency=? AND quote_currency='NOK'
          AND substr(observed_at,1,10) <= ? AND substr(observed_at,1,10) >= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1
        """,
        (currency, movement_date, floor),
    ).fetchone()


def _upsert_program_and_buyback(connection, event: dict[str, Any], document_id: int) -> int:
    program_external_id = f"newsweb-otec-{event['key']}"
    connection.execute(
        """
        INSERT INTO buyback_programs(
            external_program_id, announced_at, start_date, end_date, max_shares,
            status, source_document_id, notes
        ) VALUES (?, ?, ?, ?, ?, 'COMPLETED', ?, ?)
        ON CONFLICT(external_program_id) DO UPDATE SET
            announced_at=excluded.announced_at,
            start_date=excluded.start_date,
            end_date=excluded.end_date,
            max_shares=excluded.max_shares,
            status='COMPLETED',
            source_document_id=excluded.source_document_id,
            notes=excluded.notes
        """,
        (
            program_external_id,
            event["published_at"],
            event["program_start"],
            event["trade_date"],
            event["shares"],
            document_id,
            "Historical all-shareholder tender/bookbuild buyback; exact completion terms from Oslo Børs NewsWeb.",
        ),
    )
    program_id = int(connection.execute(
        "SELECT id FROM buyback_programs WHERE external_program_id=?", (program_external_id,)
    ).fetchone()["id"])
    amount = Decimal(event["shares"]) * event["price_nok"]
    row = connection.execute(
        "SELECT id FROM buybacks WHERE trade_date=? AND source_document_id=?",
        (event["trade_date"], document_id),
    ).fetchone()
    values = (
        program_id,
        event["shares"],
        decimal_text(event["price_nok"]),
        decimal_text(amount),
        event["shares"],
        decimal_text(event["price_nok"]),
        decimal_text(amount),
        event["treasury_after"],
    )
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO buybacks(
                program_id, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, cumulative_program_avg_price_nok,
                cumulative_program_amount_nok, treasury_shares_after, source_document_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (values[0], event["trade_date"], *values[1:], document_id),
        )
        return int(cursor.lastrowid)
    buyback_id = int(row["id"])
    connection.execute(
        """
        UPDATE buybacks SET
            program_id=?, shares=?, avg_price_nok=?, amount_nok=?,
            cumulative_program_shares=?, cumulative_program_avg_price_nok=?,
            cumulative_program_amount_nok=?, treasury_shares_after=?, source_document_id=?
        WHERE id=?
        """,
        (*values, document_id, buyback_id),
    )
    return buyback_id


def _upsert_buyback_cash(connection, event: dict[str, Any], document_id: int, buyback_id: int) -> int:
    amount = Decimal(event["shares"]) * event["price_nok"]
    row = connection.execute(
        "SELECT id FROM cash_movements WHERE buyback_id=? AND movement_type='OTELLO_BUYBACK' LIMIT 1",
        (buyback_id,),
    ).fetchone()
    values = (
        event["trade_date"],
        decimal_text(-amount),
        decimal_text(-amount),
        "NOK",
        "1",
        f"Otello historical tender buyback: {event['shares']:,} shares at NOK {event['price_nok']} per share.",
        document_id,
        buyback_id,
    )
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, amount_original, currency,
                fx_rate_to_nok, description, source_document_id, confidence, buyback_id
            ) VALUES (?, 'OTELLO_BUYBACK', ?, ?, ?, ?, ?, ?, 'CONFIRMED', ?)
            """,
            values,
        )
        return int(cursor.lastrowid)
    movement_id = int(row["id"])
    connection.execute(
        """
        UPDATE cash_movements SET movement_date=?, amount_nok=?, amount_original=?,
            currency=?, fx_rate_to_nok=?, description=?, source_document_id=?,
            confidence='CONFIRMED', buyback_id=? WHERE id=?
        """,
        (*values, movement_id),
    )
    return movement_id


def _upsert_share_count(connection, event: dict[str, Any], document_id: int) -> int:
    outstanding = event["total_shares"] - event["treasury_shares"]
    row = connection.execute(
        """
        SELECT id FROM otello_share_counts
        WHERE effective_from=? AND source_document_id=? ORDER BY id LIMIT 1
        """,
        (event["effective_from"], document_id),
    ).fetchone()
    values = (
        event["total_shares"], event["treasury_shares"], outstanding, event["notes"]
    )
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO otello_share_counts(
                effective_from, effective_to, total_shares, treasury_shares,
                outstanding_shares, source_document_id, notes
            ) VALUES (?, NULL, ?, ?, ?, ?, ?)
            """,
            (event["effective_from"], *values[:3], document_id, values[3]),
        )
        return int(cursor.lastrowid)
    share_count_id = int(row["id"])
    connection.execute(
        """
        UPDATE otello_share_counts SET effective_to=NULL, total_shares=?, treasury_shares=?,
            outstanding_shares=?, source_document_id=?, notes=? WHERE id=?
        """,
        (*values[:3], document_id, values[3], share_count_id),
    )
    return share_count_id


def seed_2021_newsweb_events(database_path: str | None = None) -> dict[str, Any]:
    """Seed verified 2021 NewsWeb events that materially affect cash/share-denominator history.

    Tender amounts are exact arithmetic from the published completion terms. The USD
    AdColony receipt is converted with the nearest prior ECB USD/NOK rate. All writes are
    idempotent. This function intentionally does not infer amounts from vague archive
    classifications.
    """
    result: dict[str, Any] = {
        "buybacks": [],
        "share_counts": [],
        "adcolony_payment": None,
        "missing_fx": [],
    }
    with get_connection(database_path) as connection:
        documents: dict[int, int] = {}
        for event in TENDER_BUYBACKS:
            document_id = _newsweb_document(
                connection,
                message_id=event["message_id"],
                title=event["title"],
                published_at=event["published_at"],
                event_key=event["key"],
            )
            documents[event["message_id"]] = document_id
            buyback_id = _upsert_program_and_buyback(connection, event, document_id)
            movement_id = _upsert_buyback_cash(connection, event, document_id, buyback_id)
            result["buybacks"].append({
                "trade_date": event["trade_date"],
                "shares": event["shares"],
                "price_nok": decimal_text(event["price_nok"]),
                "amount_nok": decimal_text(Decimal(event["shares"]) * event["price_nok"]),
                "buyback_id": buyback_id,
                "cash_movement_id": movement_id,
            })

        for event in SHARE_COUNT_EVENTS:
            document_id = documents.get(event["message_id"])
            if document_id is None:
                document_id = _newsweb_document(
                    connection,
                    message_id=event["message_id"],
                    title=event["title"],
                    published_at=event["published_at"],
                    event_key=f"share-count-{event['effective_from']}",
                )
                documents[event["message_id"]] = document_id
            share_count_id = _upsert_share_count(connection, event, document_id)
            result["share_counts"].append({
                "effective_from": event["effective_from"],
                "total_shares": event["total_shares"],
                "treasury_shares": event["treasury_shares"],
                "outstanding_shares": event["total_shares"] - event["treasury_shares"],
                "share_count_id": share_count_id,
            })

        event = ADCOLONY_PAYMENT
        document_id = _newsweb_document(
            connection,
            message_id=event["message_id"],
            title=event["title"],
            published_at=event["published_at"],
            event_key="adcolony-second-installment-2021-10-27",
        )
        fx = _nearest_fx(connection, event["currency"], event["movement_date"])
        if fx is None:
            result["missing_fx"].append({
                "movement_date": event["movement_date"], "currency": event["currency"]
            })
        else:
            original = event["amount_original"]
            fx_rate = Decimal(fx["rate"])
            amount_nok = original * fx_rate
            row = connection.execute(
                """
                SELECT id FROM cash_movements
                WHERE movement_date=? AND movement_type='OTHER' AND source_document_id=?
                ORDER BY id LIMIT 1
                """,
                (event["movement_date"], document_id),
            ).fetchone()
            values = (
                decimal_text(amount_nok), decimal_text(original), event["currency"],
                decimal_text(fx_rate),
                "Second AdColony installment: NewsWeb confirms USD 100m received by Otello on 27 Oct 2021.",
                document_id,
            )
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO cash_movements(
                        movement_date, movement_type, amount_nok, amount_original, currency,
                        fx_rate_to_nok, description, source_document_id, confidence
                    ) VALUES (?, 'OTHER', ?, ?, ?, ?, ?, ?, 'CONFIRMED')
                    """,
                    (event["movement_date"], *values),
                )
                movement_id = int(cursor.lastrowid)
            else:
                movement_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE cash_movements SET amount_nok=?, amount_original=?, currency=?,
                        fx_rate_to_nok=?, description=?, source_document_id=?, confidence='CONFIRMED'
                    WHERE id=?
                    """,
                    (*values, movement_id),
                )
            result["adcolony_payment"] = {
                "movement_date": event["movement_date"],
                "amount_original": decimal_text(original),
                "currency": event["currency"],
                "fx_rate_to_nok": decimal_text(fx_rate),
                "fx_date": fx["rate_date"],
                "amount_nok": decimal_text(amount_nok),
                "movement_id": movement_id,
            }

        connection.commit()
    return result
