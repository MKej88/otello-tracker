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

        daily_rows = connection.execute(
            f"""
            SELECT b.id AS buyback_id, b.trade_date AS period_end,
                   b.shares AS weekly_shares,
                   d.trade_date, d.shares, d.avg_price_nok, d.amount_nok,
                   d.trade_count, d.source_document_id, d.quality
            FROM buybacks b
            JOIN buyback_daily_transactions d ON d.weekly_buyback_id = b.id
            {filter_sql}
            ORDER BY b.trade_date, b.id, d.trade_date, d.id
            """,
            params,
        ).fetchall()

        rows_by_week: dict[int, list[Any]] = {}
        for row in daily_rows:
            rows_by_week.setdefault(int(row["buyback_id"]), []).append(row)

        existing_rows = connection.execute(
            f"""
            SELECT cm.id, cm.buyback_id, cm.movement_date,
                   cm.amount_nok, cm.amount_original, cm.description,
                   cm.source_document_id, cm.confidence
            FROM cash_movements cm
            WHERE cm.movement_type = 'OTELLO_BUYBACK_DAILY'
              AND EXISTS (
                  SELECT 1
                  FROM buybacks b
                  JOIN buyback_daily_transactions d ON d.weekly_buyback_id = b.id
                  WHERE b.id = cm.buyback_id
                    {"AND b.id = ?" if weekly_buyback_id is not None else ""}
              )
            ORDER BY cm.id
            """,
            params,
        ).fetchall()
        existing_by_week_and_date: dict[tuple[int, str], Any] = {}
        existing_by_week: dict[int, list[Any]] = {}
        for row in existing_rows:
            buyback_id = int(row["buyback_id"])
            existing_by_week.setdefault(buyback_id, []).append(row)
            existing_by_week_and_date.setdefault(
                (buyback_id, str(row["movement_date"])), row
            )

        weekly_deleted = 0
        daily_written = 0
        daily_updated = 0
        synced_weeks: list[dict[str, Any]] = []

        for buyback_id, rows in rows_by_week.items():
            week = rows[0]
            daily_shares = sum(int(row["shares"]) for row in rows)
            if daily_shares != int(week["weekly_shares"]):
                raise ValueError(
                    f"NewsWeb cash-sync nekter uke {week['period_end']}: "
                    f"daglige aksjer {daily_shares} != uke {week['weekly_shares']}"
                )
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
                existing = existing_by_week_and_date.get((buyback_id, trade_date))
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
                elif (
                    Decimal(existing["amount_nok"]) != Decimal(amount)
                    or existing["amount_original"] is None
                    or Decimal(existing["amount_original"]) != Decimal(amount)
                    or existing["description"] != description
                    or existing["source_document_id"] != row["source_document_id"]
                    or existing["confidence"] != "CONFIRMED"
                ):
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

            for item in existing_by_week.get(buyback_id, []):
                if item["movement_date"] not in seen_dates:
                    connection.execute(
                        "DELETE FROM cash_movements WHERE id = ?", (item["id"],)
                    )

            synced_weeks.append(
                {
                    "buyback_id": buyback_id,
                    "period_end": week["period_end"],
                    "daily_count": len(rows),
                    "daily_shares": daily_shares,
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
