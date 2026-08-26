from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import estimated_nav_history  # noqa: E402


class Repository:
    async def first(self, sql, params=()):
        if "FROM cash_anchors" in sql:
            return {"as_of_date": "2026-03-31"}
        raise AssertionError(f"Unexpected query: {sql}")


def _install_common_stubs(monkeypatch, *, life360: dict) -> None:
    async def full_row(_repository, day):
        return {
            "date": day,
            "nav_total_nok": 140_000_000,
            "nav_per_share_nok": 14,
            "otec_price_nok": 10,
            "bemobi_value_nok": 40_000_000,
            "cash_estimate_nok": 30_000_000,
            "other_net_assets_nok": 70_000_000,
            "shares_outstanding": 10_000_000,
            "components_json": "{}",
        }

    async def nearest_fx(_repository, currency, day):
        assert currency == "USD"
        return {"rate": "10", "rate_date": day}

    async def latest_cost_anchors(_repository, _day):
        return {
            "BASE": {
                "amount_usd_decimal": "0",
                "period_days_int": 1,
            }
        }

    async def cash_fx(_repository, *, cash_anchor_date, as_of_date):
        assert cash_anchor_date == "2026-03-31"
        assert as_of_date == "2026-04-02"
        return {"ready": True, "adjustment_nok": Decimal("0")}

    async def life360_adjustment(_repository, *, as_of_date):
        assert as_of_date == "2026-04-02"
        return life360

    def settlement(*, pre_option_total_nok, shares_outstanding, option_count, strike_nok):
        assert option_count == 0
        assert strike_nok == Decimal("0")
        return {
            "settlement_nok": Decimal("0"),
            "economic_total_after_settlement_nok": pre_option_total_nok,
            "nav_after_option_per_share_nok": pre_option_total_nok / Decimal(shares_outstanding),
        }

    monkeypatch.setattr(estimated_nav_history, "_full_row", full_row)
    monkeypatch.setattr(estimated_nav_history, "_option_values", lambda _components: (Decimal("0"), Decimal("0")))
    monkeypatch.setattr(
        estimated_nav_history,
        "settlement_inputs_from_components",
        lambda _components: (0, Decimal("0")),
    )
    monkeypatch.setattr(estimated_nav_history, "_nearest_fx", nearest_fx)
    monkeypatch.setattr(estimated_nav_history, "_latest_cost_anchors", latest_cost_anchors)
    monkeypatch.setattr(estimated_nav_history, "_cash_fx_revaluation", cash_fx)
    monkeypatch.setattr(estimated_nav_history, "life360_nav_adjustment", life360_adjustment)
    monkeypatch.setattr(estimated_nav_history, "nav_cash_settlement", settlement)


def test_estimated_nav_shows_gross_life360_value_without_changing_total(monkeypatch) -> None:
    _install_common_stubs(
        monkeypatch,
        life360={
            "ready": True,
            "shares": 37_028,
            "price": Decimal("135.00"),
            "price_date": "2026-04-01",
            "price_source": "YAHOO_FINANCE",
            "fx_rate": Decimal("10"),
            "fx_date": "2026-04-02",
            "anchor_date": "2026-03-31",
            "anchor_price_usd": Decimal("108.00"),
            "anchor_price_date": "2026-03-30",
            "market_value_nok": Decimal("50000000"),
            "embedded_value_nok": Decimal("40000000"),
            "adjustment_nok": Decimal("10000000"),
        },
    )

    result = asyncio.run(estimated_nav_history._estimated_point(Repository(), "2026-04-02"))

    assert result["ready"] is True
    by_key = {item["key"]: item for item in result["composition"]}
    assert by_key["life360"]["amount_mnok"] == 50.0
    assert by_key["life360"]["per_share_nok"] == 5.0
    assert by_key["life360"]["details"]["embedded_value_mnok"] == 40.0
    assert by_key["life360"]["details"]["adjustment_mnok"] == 10.0
    assert by_key["ona"]["amount_mnok"] == 30.0
    assert by_key["ona"]["details"]["life360_embedded_removed_mnok"] == 40.0
    assert result["nav_total_mnok"] == 150.0
    assert result["nav_per_share"] == 15.0
    assert abs(result["reconciliation_residual_mnok"]) < 1e-9


def test_unavailable_life360_is_flagged_instead_of_presented_as_real_zero(monkeypatch) -> None:
    _install_common_stubs(
        monkeypatch,
        life360={
            "ready": False,
            "reason": "missing_current_lif_price",
            "shares": 37_028,
            "adjustment_nok": Decimal("0"),
        },
    )

    result = asyncio.run(estimated_nav_history._estimated_point(Repository(), "2026-04-02"))

    by_key = {item["key"]: item for item in result["composition"]}
    assert by_key["life360"]["amount_mnok"] == 0.0
    assert by_key["life360"]["details"]["active"] is False
    assert by_key["life360"]["details"]["reason"] == "missing_current_lif_price"
    assert by_key["ona"]["amount_mnok"] == 70.0
    assert result["nav_total_mnok"] == 140.0
    assert abs(result["reconciliation_residual_mnok"]) < 1e-9
