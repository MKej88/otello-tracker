from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.buybacks.older_2023 import OLDER_2023_OFFICIAL_BUYBACKS


def reconciled_older_2023_buybacks() -> list[dict]:
    """Return model-ready 2023 rows while preserving issuer-reported raw facts.

    The weekly releases occasionally differ by a few NOK from the change in the
    issuer's own cumulative program consideration. The cumulative amount is the
    stronger program-level control, so the cash model uses the cumulative-implied
    weekly amount. Share-count deltas must reconcile exactly and are never inferred.
    """
    rows: list[dict] = []
    previous_cumulative_amount = Decimal("0")
    previous_cumulative_shares = 0

    for raw in OLDER_2023_OFFICIAL_BUYBACKS:
        item = dict(raw)
        status = raw["status"]

        implied_shares = status.cumulative_program_shares - previous_cumulative_shares
        if implied_shares != status.period_shares:
            raise ValueError(
                "2023 buyback share count does not reconcile to cumulative issuer total: "
                f"period_end={status.period_end}, weekly={status.period_shares}, "
                f"cumulative_implied={implied_shares}"
            )

        implied_amount = status.cumulative_program_amount_nok - previous_cumulative_amount
        if implied_amount != status.period_amount_nok:
            item["status"] = replace(status, period_amount_nok=implied_amount)
            raw_note = item.get("source_note")
            reconciliation_note = (
                f"Issuer release states NOK {status.period_amount_nok} weekly consideration "
                f"for {status.period_start} through {status.period_end}, while the change in "
                f"the issuer's cumulative program consideration implies NOK {implied_amount}. "
                "The cash model uses the cumulative-implied amount; the raw weekly figure "
                "remains preserved in older_2023.py."
            )
            item["source_note"] = (
                f"{raw_note} {reconciliation_note}" if raw_note else reconciliation_note
            )

        rows.append(item)
        previous_cumulative_amount = status.cumulative_program_amount_nok
        previous_cumulative_shares = status.cumulative_program_shares

    return rows
