from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.buybacks.older_2023 import OLDER_2023_OFFICIAL_BUYBACKS
from app.buybacks.older_2023_h1_2024 import H1_2024_CONTINUATION


def _append_note(existing: str | None, addition: str) -> str:
    return f"{existing} {addition}" if existing else addition


def reconciled_older_2023_buybacks() -> list[dict]:
    """Return model-ready rows for the 2023 program through its 1H24 continuation.

    The weekly releases occasionally differ by a few NOK from the change in the
    issuer's own cumulative program consideration. The cumulative amount is the
    stronger program-level control, so the cash model uses the cumulative-implied
    weekly amount. Share-count deltas must reconcile exactly and are never inferred.

    This program started from zero treasury shares. Two 1H24 releases repeat the
    preceding treasury balance even though their cumulative program share counts
    increased. Those raw issuer values remain in the source transcription, while the
    model uses the cumulative share control for the treasury balance.
    """
    rows: list[dict] = []
    previous_cumulative_amount = Decimal("0")
    previous_cumulative_shares = 0
    raw_rows = [*OLDER_2023_OFFICIAL_BUYBACKS, *H1_2024_CONTINUATION]

    for raw in raw_rows:
        item = dict(raw)
        status = raw["status"]

        implied_shares = status.cumulative_program_shares - previous_cumulative_shares
        if implied_shares != status.period_shares:
            raise ValueError(
                "2023 buyback share count does not reconcile to cumulative issuer total: "
                f"period_end={status.period_end}, weekly={status.period_shares}, "
                f"cumulative_implied={implied_shares}"
            )

        model_status = status
        implied_amount = status.cumulative_program_amount_nok - previous_cumulative_amount
        if implied_amount != status.period_amount_nok:
            model_status = replace(model_status, period_amount_nok=implied_amount)
            item["source_note"] = _append_note(
                item.get("source_note"),
                (
                    f"Issuer release states NOK {status.period_amount_nok} weekly consideration "
                    f"for {status.period_start} through {status.period_end}, while the change in "
                    f"the issuer's cumulative program consideration implies NOK {implied_amount}. "
                    "The cash model uses the cumulative-implied amount; the raw weekly figure "
                    "remains preserved in the source transcription."
                ),
            )

        expected_treasury = status.cumulative_program_shares
        if model_status.treasury_shares_after != expected_treasury:
            raw_treasury = model_status.treasury_shares_after
            model_status = replace(model_status, treasury_shares_after=expected_treasury)
            item["source_note"] = _append_note(
                item.get("source_note"),
                (
                    f"Issuer release states {raw_treasury:,} treasury shares at {status.period_end}, "
                    f"while the same release reports {expected_treasury:,} cumulative program shares. "
                    "Because this program began from zero treasury shares and no intervening treasury "
                    "action is reported, the model uses the cumulative share control; the raw issuer "
                    "treasury figure remains preserved in the source transcription."
                ),
            )

        item["status"] = model_status
        rows.append(item)
        previous_cumulative_amount = status.cumulative_program_amount_nok
        previous_cumulative_shares = status.cumulative_program_shares

    return rows
