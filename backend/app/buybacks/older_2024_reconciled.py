from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.buybacks.older_2024 import OLDER_2024_OFFICIAL_BUYBACKS

AUG_11_URL_SUFFIX = "2024-08-11-otello-corporation-share-buyback-program-status"
JAN_03_URL_SUFFIX = "2025-01-03-otello-corporation-share-buyback-program-status"


def reconciled_older_2024_buybacks() -> list[dict]:
    """Return model-ready rows while preserving raw issuer facts in older_2024.py.

    Two material issuer-text inconsistencies are reconciled explicitly:

    1. 11 Aug 2024 status (week ending 9 Aug): the release states 4,074,164
       treasury shares. The verified 30 Jun base was 3,688,364 and cumulative program
       purchases were 254,200, implying 3,942,564. The preceding and following weekly
       treasury counts also reconcile to that same arithmetic sequence.

    2. 3 Jan 2025 status: the release states NOK 1,485,870 weekly consideration while
       cumulative consideration rises from NOK 29,940,308 to NOK 31,425,994, implying
       NOK 1,485,686. The cash curve uses the cumulative-implied amount because cumulative
       program totals are the coverage control.

    Raw issuer values remain untouched in older_2024.py and each model correction is
    carried in source metadata rather than silently replacing the source fact.
    """
    rows: list[dict] = []
    for raw in OLDER_2024_OFFICIAL_BUYBACKS:
        item = dict(raw)

        if raw["url"].endswith(AUG_11_URL_SUFFIX):
            item["status"] = replace(raw["status"], treasury_shares_after=3_942_564)
            item["source_note"] = (
                "Issuer release states 4,074,164 treasury shares after the week ending "
                "9 Aug 2024. The 30 Jun base of 3,688,364 plus cumulative program purchases "
                "of 254,200 equals 3,942,564; both the preceding and following weekly statuses "
                "also reconcile to this sequence. The model stores 3,942,564 while preserving "
                "the raw issuer figure in older_2024.py."
            )

        if raw["url"].endswith(JAN_03_URL_SUFFIX):
            item["status"] = replace(raw["status"], period_amount_nok=Decimal("1485686"))
            item["source_note"] = (
                "Issuer release states NOK 1,485,870 weekly consideration for 30 Dec 2024 "
                "through 3 Jan 2025, but cumulative consideration increases from NOK "
                "29,940,308 to NOK 31,425,994, implying NOK 1,485,686. The cash model uses "
                "the cumulative-reconciled amount; the raw issuer weekly amount remains "
                "preserved in older_2024.py. This week also spans the 31 Dec report anchor."
            )

        rows.append(item)
    return rows
