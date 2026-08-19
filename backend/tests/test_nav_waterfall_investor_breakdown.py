from __future__ import annotations

import asyncio
import copy
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

from app.nav_waterfall_investor import (
    _cash_breakdown as reference_cash_breakdown,
    reclassify_waterfall as reference_reclassify,
)

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from nav_waterfall_investor import (  # noqa: E402
    _cash_breakdown as worker_cash_breakdown,
    reclassify_waterfall as worker_reclassify,
)


class FakeRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    async def all(self, sql: str, params=()):
        return [dict(row) for row in self.connection.execute(sql, params).fetchall()]

    async def first(self, sql: str, params=()):
        row = self.connection.execute(sql, params).fetchone()
        return dict(row) if row is not None else None


def _cash_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE cash_movements(
            id INTEGER PRIMARY KEY,
            movement_date TEXT NOT NULL,
            movement_type TEXT NOT NULL,
            amount_nok TEXT NOT NULL,
            description TEXT,
            external_movement_id TEXT,
            buyback_id INTEGER
        )
        """
    )
    rows = [
        (1, "2026-01-02", "OTELLO_BUYBACK", "-6000000", "Otello buyback during 2025-12-29–2026-01-02", None, 1),
        (2, "2026-01-02", "OTELLO_BUYBACK_DAILY", "-2000000", "NewsWeb daily buyback", None, 1),
        (3, "2026-02-06", "OTELLO_BUYBACK", "-3000000", "Otello buyback during 2026-02-02–2026-02-06", None, 2),
        (4, "2026-02-10", "OTELLO_BUYBACK_DAILY", "-4000000", "NewsWeb daily buyback", None, 3),
        (5, "2026-05-27", "BEMOBI_JCP", "5000000", "Bemobi JCP", None, None),
        (6, "2026-05-27", "TAX", "-1000000", "Bemobi JCP withholding adjustment", "bemobi-withholding:test", None),
        (7, "2026-06-01", "BEMOBI_DIVIDEND", "10000000", "Bemobi dividend", None, None),
        (8, "2026-06-02", "TAX", "-500000", "Other tax", "other-tax", None),
    ]
    connection.executemany(
        """
        INSERT INTO cash_movements(
            id, movement_date, movement_type, amount_nok, description,
            external_movement_id, buyback_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return connection


def test_daily_buybacks_and_bemobi_cash_are_classified_separately() -> None:
    connection = _cash_connection()
    reference = reference_cash_breakdown(
        connection,
        anchor_date="2025-12-31",
        as_of_date="2026-08-19",
    )
    worker = asyncio.run(
        worker_cash_breakdown(
            FakeRepository(connection),
            anchor_date="2025-12-31",
            as_of_date="2026-08-19",
        )
    )

    assert worker == reference
    assert reference["buyback_cash_nok"] == Decimal("-9000000")
    assert reference["buyback_metadata"]["daily_cash_rows"] == 2
    assert reference["buyback_metadata"]["weekly_cash_rows"] == 1
    assert reference["buyback_metadata"]["cross_anchor_excluded"] == 1
    assert reference["bemobi_gross_cash_nok"] == Decimal("15000000")
    assert reference["bemobi_withholding_nok"] == Decimal("-1000000")


def _base_waterfall() -> dict:
    return {
        "ready": True,
        "quality": "RECONCILED",
        "anchor_date": "2025-12-31",
        "as_of_date": "2026-08-19",
        "anchor": {"shares_outstanding": 10_000_000},
        "components": [
            {
                "key": "bemobi",
                "label": "Bemobi-verdi",
                "amount_mnok": 20.0,
                "per_share_nok": 2.0,
                "impact_kind": "TOTAL_AND_PER_SHARE",
            },
            {
                "key": "buyback_cash",
                "label": "Tilbakekjøp – kontantbruk",
                "amount_mnok": -1.0,
                "per_share_nok": -0.1,
                "impact_kind": "TOTAL_AND_PER_SHARE",
            },
            {
                "key": "other_cash",
                "label": "Øvrig kontantendring",
                "amount_mnok": -49.0,
                "per_share_nok": -4.9,
                "impact_kind": "TOTAL_AND_PER_SHARE",
            },
            {
                "key": "ona_ex_option",
                "label": "ONA ekskl. opsjon",
                "amount_mnok": 20.0,
                "per_share_nok": 2.0,
                "impact_kind": "TOTAL_AND_PER_SHARE",
            },
            {
                "key": "share_count",
                "label": "Færre utestående aksjer",
                "amount_mnok": None,
                "per_share_nok": 0.5,
                "impact_kind": "PER_SHARE_ONLY",
            },
        ],
        "buybacks": {"modeled_cash_mnok": -1.0},
        "reconciliation": {"residual_mnok": 0.0, "per_share_residual_nok": 0.0},
        "note": "Base waterfall.",
    }


def _reclassify(builder):
    return builder(
        copy.deepcopy(_base_waterfall()),
        cash_change_nok=Decimal("-50000000"),
        buyback_cash_nok=Decimal("-9000000"),
        bemobi_gross_cash_nok=Decimal("15000000"),
        bemobi_withholding_nok=Decimal("-1000000"),
        anchor_bemobi_receivable_nok=Decimal("0"),
        current_bemobi_receivable_nok=Decimal("12000000"),
        buyback_metadata={"daily_cash_rows": 2, "weekly_cash_rows": 1},
        bemobi_metadata={"cash_receipt_rows": 2, "withholding_rows": 1},
    )


def test_investor_breakdown_preserves_totals_and_exposes_bemobi() -> None:
    reference = _reclassify(reference_reclassify)
    worker = _reclassify(worker_reclassify)
    assert worker == reference

    components = {item["key"]: item for item in reference["components"]}
    assert components["buyback_cash"]["amount_mnok"] == -9.0
    assert components["bemobi_cash_received"]["amount_mnok"] == 14.0
    assert components["other_cash"]["amount_mnok"] == -55.0
    assert components["bemobi_receivable"]["amount_mnok"] == 12.0
    assert components["ona_ex_option"]["amount_mnok"] == 8.0

    assert (
        components["buyback_cash"]["amount_mnok"]
        + components["bemobi_cash_received"]["amount_mnok"]
        + components["other_cash"]["amount_mnok"]
    ) == -50.0
    assert (
        components["bemobi_receivable"]["amount_mnok"]
        + components["ona_ex_option"]["amount_mnok"]
    ) == 20.0
    assert reference["bemobi_distributions"]["net_cash_mnok"] == 14.0
    assert reference["bemobi_distributions"]["current_receivable_mnok"] == 12.0


def test_routes_use_settlement_waterfall_service() -> None:
    backend = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare" / "src" / "app.py").read_text(encoding="utf-8")
    assert "from app.nav_waterfall_settlement import nav_waterfall_summary" in backend
    assert "from nav_waterfall_settlement import nav_waterfall_summary" in worker
