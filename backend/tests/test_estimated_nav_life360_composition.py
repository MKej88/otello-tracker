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
                {
                    "key": "cash",
                    "label": "Estimert kontantbeholdning",
                    "amount_mnok": 30.0,
                    "per_share_nok": 3.0,
                    "details": {
                        "reported_cash_mnok": 35.0,
                        "cash_fx_adjustment_mnok": 2.0,
                        "operating_cost_mnok": 7.0,
                        "cash_anchor_date": "2026-03-31",
                    },
                },
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


def _report_state() -> dict:
    return {
        "ready": True,
        "report_date": "2026-03-31",
        "resolved_report_anchor_date": "2026-03-31",
        "source_document_id": 90,
        "cash_source_document_id": 90,
        "reported_cash_nok": Decimal("50000000"),
        "reported_cash_original": Decimal("5000000"),
        "reported_cash_currency": "USD",
        "report_usd_nok": Decimal("10"),
        "base_other_net_assets_ex_option_usd": Decimal("6500000"),
        "other_shares_investment_usd": Decimal("6000000"),
        "life360_report_price_usd": Decimal("94.52522361456249"),
        "life360_report_price_date": "2026-03-31",
        "life360_report_price_source": "YAHOO_FINANCE",
        "life360_report_usd": Decimal("3500000"),
        "life360_report_nok": Decimal("35000000"),
        "alliance_report_usd": Decimal("2500000"),
        "alliance_report_nok": Decimal("25000000"),
        "residual_report_usd": Decimal("500000"),
        "residual_report_nok": Decimal("5000000"),
    }


async def _cash_breakdown(*_args, **_kwargs) -> dict:
    return {
        "ready": True,
        "buyback_cash_nok": Decimal("-12000000"),
        "daily_buyback_rows": 4,
        "weekly_buyback_rows": 0,
        "weekly_buyback_rows_superseded": 1,
    }


def test_confirmed_other_cash_display_exposes_patent_settlement() -> None:
    rows = [
        {
            "movement_date": "2026-07-22",
            "movement_type": "OTHER",
            "amount_nok": "6200000",
            "amount_original": "650000",
            "currency": "USD",
            "description": "Final net instalment from the 2025 patent sale",
            "external_movement_id": "otello-report-post-cash:PATENT_SALE_FINAL_INSTALMENT:2026-07-22",
            "source_document_id": 99,
        }
    ]

    confirmed, formula, events = estimated_nav_history_display._confirmed_other_cash_display(
        rows,
        Decimal("6200000"),
    )

    assert confirmed is True
    assert formula == "Patentoppgjør 22.07.2026: USD 0,65m"
    assert events[0]["amount_original"] == 650000.0
    assert events[0]["source_document_id"] == 99


def test_confirmed_other_cash_display_falls_back_if_events_do_not_reconcile() -> None:
    rows = [
        {
            "movement_date": "2026-07-22",
            "movement_type": "OTHER",
            "amount_nok": "6200000",
            "amount_original": "650000",
            "currency": "USD",
            "description": "Final net instalment from the 2025 patent sale",
            "external_movement_id": "otello-report-post-cash:PATENT_SALE_FINAL_INSTALMENT:2026-07-22",
            "source_document_id": 99,
        }
    ]

    confirmed, formula, _events = estimated_nav_history_display._confirmed_other_cash_display(
        rows,
        Decimal("6000000"),
    )

    assert confirmed is False
    assert formula == "Kjente kontantbevegelser utenom tilbakekjøp"


def test_report_cash_alliance_life360_and_residual_are_split_without_changing_nav(monkeypatch) -> None:
    async def base(_repository, *, days):
        assert days == 30
        return _base_result()

    async def life360(_repository, *, as_of_date):
        if as_of_date == "2026-04-01":
            return _state(market="45000000", embedded="35000000", day=as_of_date)
        assert as_of_date == "2026-04-02"
        return _state(market="50000000", embedded="40000000", day=as_of_date)

    async def report(_repository, report_date):
        assert report_date == "2026-03-31"
        return _report_state()

    monkeypatch.setattr(estimated_nav_history_display, "_estimated_nav_history", base)
    monkeypatch.setattr(estimated_nav_history_display, "life360_nav_adjustment", life360)
    monkeypatch.setattr(estimated_nav_history_display, "_report_split_state", report)
    monkeypatch.setattr(estimated_nav_history_display, "_cash_breakdown", _cash_breakdown)

    result = asyncio.run(
        estimated_nav_history_display.estimated_nav_history(Repository(), days=30)
    )

    current = result["current"]
    by_key = {item["key"]: item for item in current["composition"]}
    assert current["nav_total_mnok"] == 150.0
    assert current["nav_per_share"] == 15.0
    assert "cash" not in by_key
    assert "ona" not in by_key
    assert by_key["reported_cash"]["label"] == "Kontantbeholdning"
    assert by_key["reported_cash"]["amount_mnok"] == 50.0
    assert by_key["operating_cost_since_report"]["amount_mnok"] == -7.0
    assert by_key["buybacks_since_report"]["amount_mnok"] == -12.0
    assert by_key["other_cash_since_report"]["amount_mnok"] == -3.0
    assert by_key["other_cash_since_report"]["label"] == "Andre kontantbevegelser siden siste rapport"
    assert by_key["other_cash_since_report"]["details"]["confirmed"] is False
    assert by_key["fx_since_report"]["amount_mnok"] == 2.0
    assert by_key["alliance_venture_spring"]["amount_mnok"] == 25.0
    assert by_key["alliance_venture_spring"]["details"]["shares"] == 7_411_532
    assert by_key["alliance_venture_spring"]["details"]["display_policy"] == "FIXED_AT_LAST_REPORT"
    assert by_key["other_reported_assets_liabilities"]["amount_mnok"] == 5.0
    assert by_key["life360"]["amount_mnok"] == 50.0
    assert by_key["life360"]["per_share_nok"] == 5.0
    assert by_key["life360"]["formula"] == "37 028 LIF-aksjer × siste LIF-kurs × USD/NOK"
    assert sum(item["amount_mnok"] for item in current["composition"]) == 150.0
    assert current["composition_split_status"]["ready"] is True
    assert current["composition_split_status"]["anchor_fallback_used"] is False

    drivers = {item["key"]: item for item in result["change"]["drivers"]}
    assert drivers["life360"]["amount_mnok"] == 5.0
    assert drivers["life360"]["per_share_nok"] == 0.5
    assert drivers["life360"]["details"]["start_amount_mnok"] == 45.0
    assert drivers["life360"]["details"]["current_amount_mnok"] == 50.0
    assert drivers["other_ona"]["amount_mnok"] == -5.0
    assert drivers["other_ona"]["per_share_nok"] == -0.5
    assert drivers["life360"]["amount_mnok"] + drivers["other_ona"]["amount_mnok"] == 0.0
    assert result["life360_display_policy"] == "GROSS_MARKET_VALUE_WITH_REPORTED_VALUE_FALLBACK"
    assert result["composition_display_policy"] == "REPORT_CASH_ALLIANCE_AND_RESIDUAL_WITH_EXPLICIT_MOVEMENTS_AND_FX"


def test_missing_current_life360_quote_uses_last_report_value_instead_of_false_zero(monkeypatch) -> None:
    base_result = _base_result()
    life_component = next(item for item in base_result["current"]["composition"] if item["key"] == "life360")
    life_component["amount_mnok"] = 0.0
    life_component["per_share_nok"] = 0.0
    ona_component = next(item for item in base_result["current"]["composition"] if item["key"] == "ona")
    ona_component["amount_mnok"] = 80.0
    ona_component["per_share_nok"] = 8.0

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

    async def report(_repository, report_date):
        assert report_date == "2026-03-31"
        return _report_state()

    monkeypatch.setattr(estimated_nav_history_display, "_estimated_nav_history", base)
    monkeypatch.setattr(estimated_nav_history_display, "life360_nav_adjustment", life360)
    monkeypatch.setattr(estimated_nav_history_display, "_report_split_state", report)
    monkeypatch.setattr(estimated_nav_history_display, "_cash_breakdown", _cash_breakdown)

    result = asyncio.run(
        estimated_nav_history_display.estimated_nav_history(Repository(), days=30)
    )

    by_key = {item["key"]: item for item in result["current"]["composition"]}
    assert "ona" not in by_key
    assert by_key["alliance_venture_spring"]["amount_mnok"] == 25.0
    assert by_key["other_reported_assets_liabilities"]["amount_mnok"] == 5.0
    assert by_key["life360"]["amount_mnok"] == 35.0
    assert by_key["life360"]["label"] == "Life360 – siste rapportverdi"
    assert by_key["life360"]["details"]["active"] is False
    assert by_key["life360"]["details"]["display_available"] is True
    assert by_key["life360"]["details"]["mark_to_market_available"] is False
    assert by_key["life360"]["details"]["reason"] == "missing_current_lif_price"
    assert by_key["fx_since_report"]["amount_mnok"] == 17.0
    assert sum(item["amount_mnok"] for item in result["current"]["composition"]) == 150.0


class _AnchorRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def first(self, sql, parameters=()):
        self.calls.append((sql, tuple(parameters)))
        if "FROM cash_anchors" in sql:
            return {
                "id": 1,
                "as_of_date": "2026-06-30",
                "amount_nok": "100000000",
                "reported_amount": "10632000",
                "reported_currency": "USD",
                "fx_rate_to_nok": "9.4055681",
                "source_document_id": 11,
            }
        if "FROM other_net_assets_reported_anchors" in sql:
            assert "r.as_of_date<=?" in sql
            return {
                "reported_anchor_id": 2,
                "as_of_date": "2026-06-30",
                "base_other_net_assets_ex_option_reported": "2933000",
                "other_shares_investment_reported": "3936000",
                "source_document_id": 11,
                "fx_rate_to_nok": "9.4055681",
            }
        if "FROM market_prices" in sql:
            assert parameters[0] == "2026-06-30"
            return {
                "trading_date": "2026-06-30",
                "price": "55.36",
                "quality": "DIRECT",
                "source_code": "LIFE360_IR_LSEG",
            }
        raise AssertionError(sql)


def test_report_split_state_uses_latest_valid_anchor_and_1h26_other_shares() -> None:
    repository = _AnchorRepository()
    result = asyncio.run(
        estimated_nav_history_display._report_split_state(repository, "2026-06-30")
    )

    assert result["ready"] is True
    assert result["resolved_report_anchor_date"] == "2026-06-30"
    assert result["other_shares_investment_usd"] == Decimal("3936000")
    assert result["life360_report_usd"] == Decimal("2049870.08")
    assert result["alliance_report_usd"] == Decimal("1886129.92")
    assert result["residual_report_usd"] == Decimal("-1003000")
