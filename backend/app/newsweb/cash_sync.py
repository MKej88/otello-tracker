from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text


def sync_newsweb_daily_buyback_cash(
    database_path: str | None = None,
    *,
    weekly_buyback_id: int | None = None,
) -> dict[str, Any]:
    """Make transaction-level NewsWeb rows the cash source where they are available.

    The weekly `buybacks` row remains the audit/reconciliation summary. Its corresponding
    weekly `OTELLO_BUYBACK` cash movement is removed only when validated daily rows exist;
    exact daily `OTELLO_BUYBACK_DAILY` movements then replace it. Weeks without NewsWeb
    attachment detail remain untouched and continue to use the Phase 9.2 conservative
    weekly fallback.
    """
    with get_connection(database_path) as connection:
        params: tuple[Any, ...] = ()
        filter_sql = ""
        if weekly_buyback_id is not None:
            filter_sql = "WHERE b.id = ?"
            params = (weekly_buyback_id,)

        weeks = connection.execute(
            f"""
            SELECT b.id AS buyback_id, b.trade_date AS period_end,
                   COUNT(d.id) AS daily_count,
                   SUM(d.shares) AS daily_shares,
                   b.shares AS weekly_shares, b.amount_nok AS weekly_amount_nok
            FROM buybacks b
            JOIN buyback_daily_transactions d ON d.weekly_buyback_id = b.id
            {filter_sql}
            GROUP BY b.id, b.trade_date, b.shares, b.amount_nok
            ORDER BY b.trade_date, b.id
            """,
            params,
        ).fetchall()

        weekly_deleted = 0
        daily_written = 0
        daily_updated = 0
        synced_weeks: list[dict[str, Any]] = []

        for week in weeks:
            buyback_id = int(week["buyback_id"])
            if int(week["daily_shares"] or 0) != int(week["weekly_shares"]):
                raise ValueError(
                    f"NewsWeb cash-sync nekter uke {week['period_end']}: "
                    f"daglige aksjer {week['daily_shares']} != uke {week['weekly_shares']}"
                )

            rows = connection.execute(
                """
                SELECT trade_date, shares, avg_price_nok, amount_nok, trade_count,
                       source_document_id, quality
                FROM buyback_daily_transactions
                WHERE weekly_buyback_id = ?
                ORDER BY trade_date, id
                """,
                (buyback_id,),
            ).fetchall()
            if not rows:
                continue
            if any(row["quality"] == "REQUIRES_REVIEW" for row in rows):
                raise ValueError(
                    f"NewsWeb cash-sync nekter uke {week['period_end']}: daglig rad krever kontroll"
                )

            deleted = connection.execute(
                """
                DELETE FROM cash_movements
                WHERE movement_type = 'OTELLO_BUYBACK'
                  AND (buyback_id = ? OR (buyback_id IS NULL AND movement_date = ?))
                """,
                (buyback_id, week["period_end"]),
            ).rowcount
            weekly_deleted += max(deleted, 0)

            seen_dates: set[str] = set()
            for row in rows:
                trade_date = row["trade_date"]
                if trade_date in seen_dates:
                    raise ValueError(
                        f"Flere NewsWeb daily buyback-rader for samme uke/dato: {trade_date}"
                    )
                seen_dates.add(trade_date)
                amount = decimal_text(-Decimal(row["amount_nok"]))
                description = (
                    f"NewsWeb transaction-level Otello buyback: {row['shares']:,} shares "
                    f"on {trade_date}; weekly status period ending {week['period_end']}."
                )
                existing = connection.execute(
                    """
                    SELECT id FROM cash_movements
                    WHERE movement_type = 'OTELLO_BUYBACK_DAILY'
                      AND buyback_id = ? AND movement_date = ?
                    ORDER BY id LIMIT 1
                    """,
                    (buyback_id, trade_date),
                ).fetchone()
                if existing is None:
                    connection.execute(
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
                            row["source_document_id"],
                            buyback_id,
                        ),
                    )
                    daily_written += 1
                else:
                    connection.execute(
                        """
                        UPDATE cash_movements
                        SET amount_nok = ?, amount_original = ?, description = ?,
                            source_document_id = ?, confidence = 'CONFIRMED'
                        WHERE id = ?
                        """,
                        (
                            amount,
                            amount,
                            description,
                            row["source_document_id"],
                            existing["id"],
                        ),
                    )
                    daily_updated += 1

            stale = connection.execute(
                """
                SELECT id, movement_date FROM cash_movements
                WHERE movement_type = 'OTELLO_BUYBACK_DAILY' AND buyback_id = ?
                """,
                (buyback_id,),
            ).fetchall()
            for item in stale:
                if item["movement_date"] not in seen_dates:
                    connection.execute("DELETE FROM cash_movements WHERE id = ?", (item["id"],))

            synced_weeks.append(
                {
                    "buyback_id": buyback_id,
                    "period_end": week["period_end"],
                    "daily_count": len(rows),
                    "daily_shares": int(week["daily_shares"]),
                    "weekly_shares": int(week["weekly_shares"]),
                }
            )

        connection.commit()

    return {
        "weeks_synced": len(synced_weeks),
        "weekly_cash_rows_deleted": weekly_deleted,
        "daily_cash_rows_written": daily_written,
        "daily_cash_rows_updated": daily_updated,
        "weeks": synced_weeks,
    }
