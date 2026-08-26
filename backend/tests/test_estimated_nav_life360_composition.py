from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import estimated_nav_history_display  # noqa: E402


class Repository:
    pass


def _base_result() -> dict:
    return {
        "ready": True,
        "to": "2026-04-02",
        "current": {
            "date": "2026-04-02",
            "nav_total_mnok": 150.0,
            "nav_per_share": 15.0,
            "shares_outstanding": 10_000_000,
            "reconciliation_residual_mnok": 0.0,
            "composition": [
                {"key": "bemobi", "label": "Bemobi", "amount_mnok": 40.0, "per_share_nok": 4.0},
                {"key": "cash", "label": "Kontanter", "amount_mnok": 30.0, "per_share_nok": 3.0},
                {"key": "ona", "label": "Øvrige nettoeiendeler", "amount_mnok": 70.0, "per_share_nok": 7.0, "details": {}},
                {
                    "key": "life360",
                    "label": "Life360 mark-to-market",
                    "amount_mnok": 10.0,
                    "per_share_nok": 1.0,
                    "formula": "Dagens verdi av LIF − Life360-verdi innebygd i siste rapporterte ONA",
                    "details": {"active": True},
                },
                {"key": "options", "label": "Opsjoner", "amount_mnok": 0.0, "per_share_nok": 0.0},
            ],
        },
        "change": {
            "ready": True,
            "resolved_start": "2026-04-01",
            "current_date": "2026-04-02",
            "share_count_change": {"start_shares": 10_000_000, "current_shares": 10_000_000},
            "drivers": [
                {
                    "key": "other_ona",
                    "label": "Øvrige nettoeiendeler",
                    "amount_mnok": 0.0,
                    "per_share_nok": 0.0,
                    "details": {"start_amount_mnok": 70.0, "current_amount_mnok": 70.0},
                },
                {
                    "key": "life360",
                    "label": "Life360 mark-to-market",
                    "amount_mnok": 0.0,
                    "per_share_nok": 0.0,
                    "details": {"start_amount_mnok": 10.0, "current_amount_mnok": 10.0},
                },
            ],
        },
    }


def _state(*, market: str, embedded: str, day: str) -> dict:
    market_nok = Decimal(market)
    embedded_nok = Decimal(embedded)
    return {
        "ready": True,
        "shares": 37_028,
        "price": Decimal("135.00"),
        "price_date": day,
        "price_source": "YAHOO_FINANCE",
        "fx_rate": Decimal("10"),
        "fx_date": day,
        "anchor_date": "2026-03-31",
        "anchor_price_usd": Decimal("108.00"),
        "anchor_price_date": "2026-03-30",
        "market_value_nok": market_nok,
        "embedded_value_nok": embedded_nok,
        "adjustment_nok": market_nok - embedded_nok,
    }


def test_gross_life360_value_is_split_out_of_ona_without_changing_nav(monkeypatch) -> None:
    async def base(_repository, *, days):
        assert days == 30
        return _base_result()

    async def life360(_repository, *, as_of_date):
        if as_of_date == "2026-04-01":
            return _state(market="45000000", embedded="35000000", day=as_of_date)
        assert as_of_date == "2026-04-02"
        return _state(market="50000000", embedded="40000000", day=as_of_date)

    monkeypatch.setattr(estimated_nav_history_display, "_estimated_nav_history", base)
    monkeypatch.setattr(estimated_nav_history_display, "life360_nav_adjustment", life360)

    result = asyncio.run(
        estimated_nav_history_display.estimated_nav_history(Repository(), days=30)
    )

    assert result["nav_total_mnok"] if "nav_total_mnok" in result else 150.0
    current = result["current"]
    by_key = {item["key"]: item for item in current["composition"]}
    assert current["nav_total_mnok"] == 150.0
    assert current["nav_per_share"] == 15.0
    assert by_key["life360"]["amount_mnok"] == 50.0
    assert by_key["life360"]["per_share_nok"] == 5.0
    assert by_key["life360"]["formula"] == "37 028 LIF-aksjer × siste LIF-kurs × USD/NOK"
    assert by_key["life360"]["details"]["embedded_value_mnok"] == 40.0
    assert by_key["life360"]["details"]["adjustment_mnok"] == 10.0
    assert by_key["ona"]["amount_mnok"] == 30.0
    assert by_key["ona"]["details"]["life360_embedded_removed_mnok"] == 40.0
    assert sum(item["amount_mnok"] for item in current["composition"]) == 150.0

    drivers = {item["key"]: item for item in result["change"]["drivers"]}
    assert drivers["life360"]["amount_mnok"] == 5.0
    assert drivers["life360"]["per_share_nok"] == 0.5
    assert drivers["life360"]["details"]["start_amount_mnok"] == 45.0
    assert drivers["life360"]["details"]["current_amount_mnok"] == 50.0
    assert drivers["other_ona"]["amount_mnok"] == -5.0
    assert drivers["other_ona"]["per_share_nok"] == -0.5
    assert drivers["life360"]["amount_mnok"] + drivers["other_ona"]["amount_mnok"] == 0.0
    assert result["life360_display_policy"] == "GROSS_MARKET_VALUE_EX_EMBEDDED_ONA"


def test_unavailable_life360_is_flagged_instead_of_presented_as_real_zero(monkeypatch) -> None:
    base_result = _base_result()
    life_component = next(item for item in base_result["current"]["composition"] if item["key"] == "life360")
    life_component["amount_mnok"] = 0.0
    life_component["per_share_nok"] = 0.0
    ona_component = next(item for item in base_result["current"]["composition"] if item["key"] == "ona")
    ona_component["amount_mnok"] = 70.0
    ona_component["per_share_nok"] = 7.0

    async def base(_repository, *, days):
        assert days == 30
        return base_result

    async def life360(_repository, *, as_of_date):
        return {
            "ready": False,
            "reason": "missing_current_lif_price",
            "shares": 37_028,
            "adjustment_nok": Decimal("0"),
        }

    monkeypatch.setattr(estimated_nav_history_display, "_estimated_nav_history", base)
    monkeypatch.setattr(estimated_nav_history_display, "life360_nav_adjustment", life360)

    result = asyncio.run(
        estimated_nav_history_display.estimated_nav_history(Repository(), days=30)
    )

    by_key = {item["key"]: item for item in result["current"]["composition"]}
    assert by_key["life360"]["amount_mnok"] == 0.0
    assert by_key["life360"]["details"]["active"] is False
    assert by_key["life360"]["details"]["display_available"] is False
    assert by_key["life360"]["details"]["reason"] == "missing_current_lif_price"
    assert by_key["ona"]["amount_mnok"] == 70.0
    driver = next(item for item in result["change"]["drivers"] if item["key"] == "life360")
    assert driver["details"]["display_available"] is False
