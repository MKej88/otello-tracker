from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text


def buyback_coverage_gaps(
    database_path: str | None = None,
    *,
    since_date: str | None = None,
) -> list[dict[str, Any]]:
    """Detect missing weekly rows from published cumulative program totals.

    `PREFIX` means the first observed status was already mid-program. `INTERNAL` means a
    weekly row is missing between two observed statuses. When `since_date` is supplied,
    gaps whose missing activity necessarily occurred on/before that date are ignored;
    this is useful for proving cash-flow completeness after the latest reported anchor.
    """
    gaps: list[dict[str, Any]] = []
    with get_connection(database_path) as connection:
        programs = connection.execute(
            "SELECT id, external_program_id FROM buyback_programs ORDER BY start_date, id"
        ).fetchall()
        for program in programs:
            rows = connection.execute(
                """
                SELECT trade_date, shares, amount_nok, cumulative_program_shares,
                       cumulative_program_amount_nok
                FROM buybacks
                WHERE program_id = ?
                ORDER BY trade_date, id
                """,
                (program["id"],),
            ).fetchall()
            previous = None
            for current in rows:
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
                        cumulative_amount - current_amount if cumulative_amount is not None else None
                    )
                    amount_mismatch = missing_amount is not None and missing_amount != 0
                    if missing_shares != 0 or amount_mismatch:
                        # All missing prefix activity is before the first observed row.
                        if since_date is None or current["trade_date"] > since_date:
                            gaps.append(
                                {
                                    "gap_type": "PREFIX",
                                    "program": program["external_program_id"],
                                    "after_date": None,
                                    "before_date": current["trade_date"],
                                    "missing_shares": missing_shares,
                                    "missing_amount_nok": (
                                        decimal_text(missing_amount) if missing_amount is not None else None
                                    ),
                                    "current_week_shares": current_shares,
                                    "current_cumulative_shares": current_cumulative,
                                }
                            )
                    previous = current
                    continue

                expected_shares = int(previous["cumulative_program_shares"]) + current_shares
                prev_amount = previous["cumulative_program_amount_nok"]
                missing_amount = None
                if prev_amount is not None and cumulative_amount is not None:
                    expected_amount = Decimal(prev_amount) + current_amount
                    missing_amount = cumulative_amount - expected_amount
                missing_shares = current_cumulative - expected_shares
                amount_mismatch = missing_amount is not None and missing_amount != 0
                if missing_shares != 0 or amount_mismatch:
                    # If the current row itself is on/before the requested boundary, the
                    # whole internal gap is historical to that boundary.
                    if since_date is None or current["trade_date"] > since_date:
                        gaps.append(
                            {
                                "gap_type": "INTERNAL",
                                "program": program["external_program_id"],
                                "after_date": previous["trade_date"],
                                "before_date": current["trade_date"],
                                "missing_shares": missing_shares,
                                "missing_amount_nok": (
                                    decimal_text(missing_amount) if missing_amount is not None else None
                                ),
                                "previous_cumulative_shares": int(previous["cumulative_program_shares"]),
                                "current_week_shares": current_shares,
                                "current_cumulative_shares": current_cumulative,
                            }
                        )
                previous = current
    return gaps
