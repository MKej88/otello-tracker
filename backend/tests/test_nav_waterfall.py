from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from app.nav_waterfall import build_nav_waterfall as reference_waterfall

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from nav_waterfall import build_nav_waterfall as worker_waterfall  # noqa: E402


def _fixture(builder):
    return builder(
        anchor_date="2025-12-31",
        as_of_date="2026-08-19",
        anchor_nav_total_nok=Decimal("100000000"),
        anchor_bemobi_value_nok=Decimal("60000000"),
        anchor_cash_nok=Decimal("30000000"),
        anchor_other_net_assets_nok=Decimal("10000000"),
        anchor_shares_outstanding=10_000_000,
        anchor_accounting_option_nok=Decimal("2000000"),
        anchor_economic_option_nok=Decimal("3000000"),
        current_nav_total_nok=Decimal("110000000"),
        current_bemobi_value_nok=Decimal("75000000"),
        current_cash_nok=Decimal("24000000"),
        current_other_net_assets_nok=Decimal("11000000"),
        current_shares_outstanding=9_000_000,
        current_accounting_option_nok=Decimal("4000000"),
        current_economic_option_nok=Decimal("6000000"),
        buyback_cash_nok=Decimal("-4000000"),
        cash_fx_adjustment_nok=Decimal("2000000"),
        operating_cost_nok=Decimal("3000000"),
        buyback_movement_count=4,
        cross_anchor_buybacks_excluded=0,
    )


def test_waterfall_reconciles_total_and_per_share() -> None:
    result = _fixture(reference_waterfall)

    assert result["ready"] is True
    assert result["quality"] == "RECONCILED"
    assert result["anchor"]["economic_nav_total_mnok"] == 99.0
    assert result["current"]["economic_nav_total_mnok"] == 107.0
    assert result["change"]["economic_nav_total_mnok"] == 8.0
    assert result["reconciliation"]["residual_mnok"] == 0.0
    assert abs(result["reconciliation"]["per_share_residual_nok"]) < 1e-12

    components = {item["key"]: item for item in result["components"]}
    assert components["bemobi"]["amount_mnok"] == 15.0
    assert components["buyback_cash"]["amount_mnok"] == -4.0
    assert components["other_cash"]["amount_mnok"] == -2.0
    assert components["ona_ex_option"]["amount_mnok"] == 3.0
    assert components["accounting_option"]["amount_mnok"] == -2.0
    assert components["cash_fx"]["amount_mnok"] == 2.0
    assert components["option_overhang"]["amount_mnok"] == -1.0
    assert components["operating_costs"]["amount_mnok"] == -3.0
    assert components["share_count"]["per_share_nok"] > 1.18


def test_worker_and_reference_waterfall_are_identical() -> None:
    assert _fixture(worker_waterfall) == _fixture(reference_waterfall)


def test_waterfall_routes_are_exposed() -> None:
    backend = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare" / "src" / "app.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "src" / "NavWaterfallPanel.tsx").read_text(encoding="utf-8")

    assert '@app.get("/api/dashboard/waterfall")' in backend
    assert '@app.get("/api/dashboard/waterfall")' in worker
    assert 'fetch("/api/dashboard/waterfall")' in frontend
    assert "Tilbakekjøp – kontantbruk" in (ROOT / "backend" / "app" / "nav_waterfall.py").read_text(encoding="utf-8")
    assert "Færre utestående aksjer" in (ROOT / "backend" / "app" / "nav_waterfall.py").read_text(encoding="utf-8")


def test_frontend_presents_buybacks_as_net_per_share_effect() -> None:
    frontend = (ROOT / "frontend" / "src" / "NavWaterfallPanel.tsx").read_text(encoding="utf-8")

    assert 'label: "Tilbakekjøp – netto effekt"' in frontend
    assert "const netImpact = cashImpact + shareCountImpact" in frontend
    assert 'label: "Kontantbruk"' in frontend
    assert 'label: "Færre aksjer"' in frontend
    assert 'if (item.key === "share_count") continue' in frontend
