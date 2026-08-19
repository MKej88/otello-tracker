from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

from app.history.economic_nav_inputs import load_economic_nav_inputs_manifest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.economic_nav import _cash_fx_revaluation as worker_cash_fx_revaluation  # noqa: E402


class FakeRepository:
    def __init__(self, anchor: dict):
        self.anchor = anchor

    async def all(self, query: str, params=()):
        assert "ECONOMIC_NAV_CASH_FX_ANCHOR" in query
        return [{"id": 77, "metadata_json": json.dumps(self.anchor)}]

    async def first(self, query: str, params=()):
        assert "FROM fx_rates" in query
        base, day, _floor = params
        rates = {
            ("USD", "2025-12-31"): {"id": 1, "rate_date": "2025-12-31", "rate": "10"},
            ("BRL", "2025-12-31"): {"id": 2, "rate_date": "2025-12-31", "rate": "2"},
            ("USD", "2026-01-31"): {"id": 3, "rate_date": "2026-01-31", "rate": "11"},
            ("BRL", "2026-01-31"): {"id": 4, "rate_date": "2026-01-31", "rate": "2.2"},
        }
        return rates.get((base, day))


def test_2025_manifest_reconciles_full_cash_to_usd_brl_nok() -> None:
    manifest = load_economic_nav_inputs_manifest()
    anchor = next(
        item for item in manifest["cash_fx_exposure_anchors"]
        if item["as_of_date"] == "2025-12-31"
    )

    exposures = {item["currency"]: item for item in anchor["exposures"]}
    assert set(exposures) == {"USD", "BRL", "NOK"}
    assert exposures["USD"]["usd_equivalent"] == "1217000"
    assert exposures["BRL"]["usd_equivalent"] == "12169000"
    assert exposures["NOK"]["usd_equivalent"] == "2495000"
    assert exposures["NOK"]["quality"] == "RECONCILED_RESIDUAL_NOK"

    total = sum(
        (Decimal(str(item["usd_equivalent"])) for item in anchor["exposures"]),
        Decimal("0"),
    )
    assert total == Decimal(anchor["total_cash_usd"]) == Decimal("15881000")


def test_worker_revalues_usd_brl_and_keeps_source_backed_nok_fixed() -> None:
    anchor = {
        "as_of_date": "2025-12-31",
        "total_cash_usd": "6000000",
        "allocation_quality": "FULL_SOURCE_BACKED",
        "policy": "REVALUE_SOURCE_BACKED_USD_BRL_KEEP_NOK_FIXED_KEEP_UNALLOCATED_FIXED",
        "exposures": [
            {"currency": "USD", "usd_equivalent": "1000000", "quality": "REPORTED_CURRENCY_EXPOSURE"},
            {"currency": "BRL", "usd_equivalent": "2000000", "quality": "REPORTED_CURRENCY_EXPOSURE"},
            {"currency": "NOK", "usd_equivalent": "3000000", "quality": "RECONCILED_RESIDUAL_NOK"},
        ],
    }

    result = asyncio.run(
        worker_cash_fx_revaluation(
            FakeRepository(anchor),
            cash_anchor_date="2025-12-31",
            as_of_date="2026-01-31",
        )
    )

    assert result["ready"] is True
    assert result["adjustment_nok"] == Decimal("3000000")
    details = result["details"]
    assert details["quality"] == "FULL_EXPOSURE_REVALUATION"
    assert details["allocation_quality"] == "FULL_SOURCE_BACKED"
    assert details["coverage_pct"] == 100.0

    components = {item["currency"]: item for item in details["components"]}
    assert components["USD"]["adjustment_mnok"] == 1.0
    assert components["BRL"]["adjustment_mnok"] == 2.0
    assert components["NOK"]["adjustment_mnok"] == 0.0
    assert components["NOK"]["original_currency_amount"] == 30_000_000.0
    assert components["NOK"]["anchor_value_mnok"] == components["NOK"]["current_value_mnok"] == 30.0


def test_frontend_and_reference_model_accept_explicit_nok_component() -> None:
    reference = (ROOT / "backend" / "app" / "economic_nav.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare" / "src" / "economic_nav.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "src" / "EconomicNavPanel.tsx").read_text(encoding="utf-8")
    migration = (ROOT / "cloudflare" / "migrations" / "0007_reconcile_2025_cash_fx_nok.sql").read_text(
        encoding="utf-8"
    )

    for source in (reference, worker):
        assert '{"NOK", "USD", "BRL", "UNALLOCATED"}' in source
        assert 'elif currency == "NOK"' in source
        assert '"FULL_EXPOSURE_REVALUATION"' in source

    assert 'item.currency === "NOK"' in frontend
    assert "Avstemt NOK-residual" in frontend
    assert "economic-nav-cash-fx:2025-12-31" in migration
    assert "RECONCILED_RESIDUAL_NOK" in migration
