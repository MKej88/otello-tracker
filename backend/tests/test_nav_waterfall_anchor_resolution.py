from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

from app import nav_waterfall_live as reference_live

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import nav_waterfall_live as worker_live  # noqa: E402


CORE_RESULT = {
    "ready": True,
    "nav_total_nok": Decimal("100000000"),
    "bemobi_value_nok": Decimal("70000000"),
    "cash_nok": Decimal("30000000"),
    "shares_outstanding": 10_000_000,
    "components": {
        "bmob3": {
            "price_date": "2025-12-30",
            "brl_nok_date": "2025-12-30",
        },
        "otec": {"price_date": "2025-12-30"},
        "cash": {"quality": "REPORTED"},
    },
}

ONA_ROW = {
    "estimate_date": "2025-12-31",
    "amount_nok": "5000000",
    "quality": "REPORTED_ANCHOR",
    "option_liability_nok": "2000000",
    "option_liability_usd": "200000",
    "option_fair_value_per_option_nok": "0.75",
    "option_recognition_fraction": "1",
    "option_spot_nok": "17",
    "option_strike_nok": "12.56",
    "option_quality": "REPORTED_CALIBRATED",
    "option_inputs_json": json.dumps(
        {
            "gross_fair_value_nok": "3000000",
            "option_count": 4_000_000,
        }
    ),
}


class _Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def execute(self, sql: str, parameters=()):
        assert "other_net_assets_daily_estimates" in sql
        assert parameters == ("2025-12-31",)
        return _Cursor(ONA_ROW)


class FakeRepository:
    async def first(self, sql: str, parameters=()):
        assert "other_net_assets_daily_estimates" in sql
        assert parameters == ("2025-12-31",)
        return dict(ONA_ROW)


def test_report_anchor_can_be_synthesized_without_stored_full_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        reference_live,
        "calculate_daily_core_nav",
        lambda _connection, _day: dict(CORE_RESULT),
    )

    row, options, resolution = reference_live._synthesize_report_anchor(
        FakeConnection(), "2025-12-31"
    )

    assert row is not None
    assert row["nav_total_nok"] == Decimal("105000000")
    assert row["nav_per_share_nok"] == Decimal("10.5")
    assert row["bemobi_value_nok"] == Decimal("70000000")
    assert row["cash_estimate_nok"] == Decimal("30000000")
    assert row["other_net_assets_nok"] == Decimal("5000000")
    assert options == (Decimal("2000000"), Decimal("3000000"))
    assert resolution["mode"] == "SYNTHESIZED_REPORT_ANCHOR"
    assert resolution["report_date"] == "2025-12-31"
    assert resolution["bmob3_market_date"] == "2025-12-30"
    assert resolution["otec_market_date"] == "2025-12-30"
    assert resolution["cash_quality"] == "REPORTED"
    assert resolution["ona_quality"] == "REPORTED_ANCHOR"


def test_worker_report_anchor_synthesis_matches_reference(monkeypatch) -> None:
    async def fake_core(_repository, _day):
        return dict(CORE_RESULT)

    monkeypatch.setattr(worker_live, "calculate_core_nav", fake_core)
    monkeypatch.setattr(
        reference_live,
        "calculate_daily_core_nav",
        lambda _connection, _day: dict(CORE_RESULT),
    )

    expected = reference_live._synthesize_report_anchor(FakeConnection(), "2025-12-31")
    actual = asyncio.run(
        worker_live._synthesize_report_anchor(FakeRepository(), "2025-12-31")
    )
    assert actual == expected


def test_waterfall_is_rendered_once_and_routes_use_resilient_service() -> None:
    economic = (ROOT / "frontend" / "src" / "EconomicNavPanel.tsx").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    backend = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare" / "src" / "app.py").read_text(encoding="utf-8")

    assert "NavWaterfallPanel" not in economic
    assert app.count("<NavWaterfallPanel />") == 1
    assert "from app.nav_waterfall_settlement import nav_waterfall_summary" in backend
    assert "from nav_waterfall_settlement import nav_waterfall_summary" in worker
