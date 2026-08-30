from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text

AMOUNT_TOLERANCE_NOK = Decimal("1")


def buyback_coverage_gaps(
    database_path: str | None = None,
    *,
    since_date: str | None = None,
) -> list[dict[str, Any]]:
    """Detect missing weekly rows from published cumulative program totals.

    `PREFIX` means the first observed status was already mid-program. `INTERNAL` means a
    weekly row is missing between two observed statuses. Share counts have zero tolerance.
    Published cumulative NOK totals occasionally differ by one krone from the sum of
    rounded weekly totals, so amount-only differences of +/-1 NOK are not treated as gaps.

    When `since_date` is supplied, gaps whose missing activity necessarily occurred
    on/before that date are ignored; this proves cash-flow completeness after an anchor.
    """
    gaps: list[dict[str, Any]] = []
    with get_connection(database_path) as connection:
        rows = connection.execute("""
            SELECT p.id AS program_id, p.external_program_id, b.trade_date,
                   b.shares, b.amount_nok, b.cumulative_program_shares,
                   b.cumulative_program_amount_nok
            FROM buyback_programs AS p
            JOIN buybacks AS b ON b.program_id = p.id
            ORDER BY p.start_date, p.id, b.trade_date, b.id
            """).fetchall()
        previous = None
        previous_program_id = None
        for current in rows:
            if current["program_id"] != previous_program_id:
                previous = None
                previous_program_id = current["program_id"]

            program_name = current["external_program_id"]
            current_shares = int(current["shares"])
            current_cumulative = int(current["cumulative_program_shares"])
            current_amount = Decimal(current["amount_nok"])
            cumulative_amount = (
                Decimal(current["cumulative_program_amount_nok"])
                if current["cumulative_program_amount_nok"] is not None
                else None
            )

            if previous is None:
                missing_shares = current_cumulative - current_shares
                missing_amount = (
                    cumulative_amount - current_amount
                    if cumulative_amount is not None
                    else None
                )
                amount_mismatch = (
                    missing_amount is not None
                    and abs(missing_amount) > AMOUNT_TOLERANCE_NOK
                )
                if missing_shares != 0 or amount_mismatch:
                    if since_date is None or current["trade_date"] > since_date:
                        gaps.append(
                            {
                                "gap_type": "PREFIX",
                                "program": program_name,
                                "after_date": None,
                                "before_date": current["trade_date"],
                                "missing_shares": missing_shares,
                                "missing_amount_nok": (
                                    decimal_text(missing_amount)
                                    if missing_amount is not None
                                    else None
                                ),
                                "current_week_shares": current_shares,
                                "current_cumulative_shares": current_cumulative,
                            }
                        )
                previous = current
                continue

            expected_shares = (
                int(previous["cumulative_program_shares"]) + current_shares
            )
            prev_amount = previous["cumulative_program_amount_nok"]
            missing_amount = None
            if prev_amount is not None and cumulative_amount is not None:
                expected_amount = Decimal(prev_amount) + current_amount
                missing_amount = cumulative_amount - expected_amount
            missing_shares = current_cumulative - expected_shares
            amount_mismatch = (
                missing_amount is not None
                and abs(missing_amount) > AMOUNT_TOLERANCE_NOK
            )
            if missing_shares != 0 or amount_mismatch:
                if since_date is None or current["trade_date"] > since_date:
                    gaps.append(
                        {
                            "gap_type": "INTERNAL",
                            "program": program_name,
                            "after_date": previous["trade_date"],
                            "before_date": current["trade_date"],
                            "missing_shares": missing_shares,
                            "missing_amount_nok": (
                                decimal_text(missing_amount)
                                if missing_amount is not None
                                else None
                            ),
                            "previous_cumulative_shares": int(
                                previous["cumulative_program_shares"]
                            ),
                            "current_week_shares": current_shares,
                            "current_cumulative_shares": current_cumulative,
                        }
                    )
            previous = current
    return gaps
