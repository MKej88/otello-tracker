from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text


def buyback_coverage_gaps(database_path: str | None = None) -> list[dict[str, Any]]:
    """Detect missing weekly rows from Otello's published cumulative program totals.

    A complete sequence must satisfy, within the same program:
      previous cumulative shares + current weekly shares == current cumulative shares
    and equivalently for cumulative cash consideration.

    The first observed row in each program cannot prove earlier coverage and is therefore
    not treated as a gap. Later mismatches are surfaced; nothing is silently imputed.
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
                if previous is not None:
                    expected_shares = int(previous["cumulative_program_shares"]) + int(current["shares"])
                    actual_shares = int(current["cumulative_program_shares"])
                    prev_amount = previous["cumulative_program_amount_nok"]
                    curr_amount = current["cumulative_program_amount_nok"]
                    expected_amount = None
                    missing_amount = None
                    if prev_amount is not None and curr_amount is not None:
                        expected_amount = Decimal(prev_amount) + Decimal(current["amount_nok"])
                        missing_amount = Decimal(curr_amount) - expected_amount
                    missing_shares = actual_shares - expected_shares
                    amount_mismatch = missing_amount is not None and missing_amount != 0
                    if missing_shares != 0 or amount_mismatch:
                        gaps.append(
                            {
                                "program": program["external_program_id"],
                                "after_date": previous["trade_date"],
                                "before_date": current["trade_date"],
                                "missing_shares": missing_shares,
                                "missing_amount_nok": (
                                    decimal_text(missing_amount) if missing_amount is not None else None
                                ),
                                "previous_cumulative_shares": int(previous["cumulative_program_shares"]),
                                "current_week_shares": int(current["shares"]),
                                "current_cumulative_shares": actual_shares,
                            }
                        )
                previous = current
    return gaps
