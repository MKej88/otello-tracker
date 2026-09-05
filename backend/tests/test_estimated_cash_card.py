from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.economic_nav import build_cash_bridge

ROOT = Path(__file__).resolve().parents[2]


def test_cash_bridge_reconciles_all_identified_movements() -> None:
    bridge = build_cash_bridge(
        anchor_date="2026-06-30",
        reported_cash_nok=Decimal("126400000"),
        modeled_cash_nok=Decimal("109300000"),
        shares_outstanding=69_500_000,
        bemobi_cash_nok=Decimal("9400000"),
        patent_proceeds_nok=Decimal("6200000"),
        buyback_cash_nok=Decimal("-28700000"),
        operating_cost_nok=Decimal("3100000"),
        cash_fx_nok=Decimal("-2400000"),
    )

    amounts = {item["key"]: item["amount_mnok"] for item in bridge["movements"]}
    assert bridge["reported_cash_mnok"] == 126.4
    assert bridge["estimated_cash_mnok"] == 103.8
    assert bridge["cash_per_share_nok"] == 103_800_000 / 69_500_000
    assert amounts == {
        "bemobi_payments": 9.4,
        "patent_proceeds": 6.2,
        "buybacks": -28.7,
        "operating_costs": -3.1,
        "cash_fx": -2.4,
        "other_cash": -4.0,
    }
    assert sum(amounts.values()) == pytest.approx(bridge["change_since_report_mnok"])
    assert bridge["reported_cash_mnok"] + bridge[
        "change_since_report_mnok"
    ] == pytest.approx(bridge["estimated_cash_mnok"])
    assert bridge["reconciles"] is True


def test_cash_bridge_filters_residual_and_handles_missing_shares() -> None:
    immaterial = build_cash_bridge(
        anchor_date="2026-06-30",
        reported_cash_nok=Decimal("100000000"),
        modeled_cash_nok=Decimal("100000500"),
        shares_outstanding=0,
    )
    material = build_cash_bridge(
        anchor_date="2026-06-30",
        reported_cash_nok=Decimal("100000000"),
        modeled_cash_nok=Decimal("100001001"),
        shares_outstanding=1,
    )

    assert immaterial["movements"] == []
    assert immaterial["cash_per_share_nok"] is None
    assert immaterial["reconciles"] is True
    assert [item["key"] for item in material["movements"]] == ["other_cash"]


def test_worker_cash_bridge_has_backend_parity() -> None:
    spec = importlib.util.spec_from_file_location(
        "worker_economic_nav", ROOT / "cloudflare/src/economic_nav.py"
    )
    assert spec is not None and spec.loader is not None
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)

    arguments = {
        "anchor_date": "2026-06-30",
        "reported_cash_nok": Decimal("100000000"),
        "modeled_cash_nok": Decimal("105000000"),
        "shares_outstanding": 50_000_000,
        "bemobi_cash_nok": Decimal("8000000"),
        "buyback_cash_nok": Decimal("-3000000"),
        "operating_cost_nok": Decimal("1000000"),
        "cash_fx_nok": Decimal("500000"),
    }
    assert worker.build_cash_bridge(**arguments) == build_cash_bridge(**arguments)


def test_overview_cash_card_is_compact_and_links_to_cash_page() -> None:
    page = (ROOT / "frontend/src/OverviewPage.tsx").read_text(encoding="utf-8")

    assert 'className="card overviewCapitalCard"' in page
    assert '<span className="label">CASH</span>' in page
    assert "mill. kr" in page
    assert "kr / OTEC-aksje" in page
    assert "Endring siden siste rapport" in page
    assert "Se cash og kapitalallokering" in page
    assert 'href="#cash"' in page
    assert "cashBridge?.movements" not in page
    assert 'return "—"' in page


def test_worker_invalidates_old_cached_economic_payload() -> None:
    source = (ROOT / "cloudflare/src/dashboard_hot_snapshot.py").read_text(
        encoding="utf-8"
    )

    assert 'STATE_KEY = "dashboard_hot_snapshot_v6"' in source
    assert "SNAPSHOT_VERSION = 6" in source


def test_worker_reference_fixture_supports_report_anchors_in_original_currency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(ROOT)
    from cloudflare.tools.build_worker_runtime_fixture import (
        build_worker_runtime_fixture,
    )

    result = build_worker_runtime_fixture(
        str(tmp_path / "reference.db"), tmp_path / "expected"
    )
    economic = json.loads((tmp_path / "expected/economic.json").read_text())

    assert result["economic_ready"] is True
    assert economic["cash_bridge"]["reported_cash_mnok"] == 160.08048
