from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.buybacks.older_2025 import OLDER_2025_OFFICIAL_BUYBACKS

MAY_23_URL_SUFFIX = "2025-05-23-otello-corporation-share-buyback-program-status"


def reconciled_older_2025_buybacks() -> list[dict]:
    """Return model-ready rows while preserving raw issuer facts in older_2025.py.

    The 23 May 2025 issuer release is internally inconsistent:
    - weekly amount in prose: NOK 4,410,701
    - prior cumulative amount: NOK 25,549,082
    - new cumulative amount: NOK 29,956,543
    - implied weekly amount from cumulative figures: NOK 4,407,461

    For the cash curve we use the cumulative-implied amount because cumulative program
    totals are the coverage control. The raw published weekly amount remains untouched in
    `older_2025.py`, and the correction is explicitly documented in source metadata.
    """
    rows: list[dict] = []
    for raw in OLDER_2025_OFFICIAL_BUYBACKS:
        item = dict(raw)
        if raw["url"].endswith(MAY_23_URL_SUFFIX):
            item["status"] = replace(raw["status"], period_amount_nok=Decimal("4407461"))
            item["source_note"] = (
                "Issuer release states NOK 4,410,701 weekly consideration, but the same "
                "release gives cumulative NOK 29,956,543 versus NOK 25,549,082 in the "
                "preceding status, implying NOK 4,407,461. The cash model stores the "
                "cumulative-reconciled value; raw issuer weekly amount remains preserved "
                "in older_2025.py."
            )
        rows.append(item)
    return rows
