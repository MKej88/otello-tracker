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


def _state(*, market: str, embedded: str, day: str, shares: int = 37_028) -> dict:
    market_nok = Decimal(market)
    embedded_nok = Decimal(embedded)
    return {
        "ready": True,
        "shares": shares,
        "anchor_shares": 37_028,
        "holding_effective_from": "2025-12-31" if shares == 37_028 else "2026-04-02",
        "holding_effective_to": None,
        "holding_quality": "DERIVED_HIGH_CONFIDENCE",
        "holding_basis": "DERIVED_FROM_2025_FAIR_VALUE",
        "holding_source_document_id": 90,
        "holding_source_locator": "Annual Report 2025, Note 4",
        "anchor_holding_effective_from": "2025-12-31",
        "anchor_holding_effective_to": None,
        "anchor_holding_quality": "DERIVED_HIGH_CONFIDENCE",
        "anchor_holding_basis": "DERIVED_FROM_2025_FAIR_VALUE",
        "anchor_holding_source_document_id": 90,
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


def _report_state(*, report_shares: int = 37_028) -> dict:
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
        "life360_report_shares": report_shares,
        "life360_holding_effective_from": "2025-12-31",
        "life360_holding_effective_to": None,
        "life360_holding_quality": "DERIVED_HIGH_CONFIDENCE",
        "life360_holding_basis": "DERIVED_FROM_2025_FAIR_VALUE",
        "life360_holding_source_document_id": 90,
        "life360_holding_source_locator": "Annual Report 2025, Note 4",
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


def test_display_date_formats_iso_date_for_norwegian_readers() -> None:
    assert estimated_nav_history_display._display_date("2026-06-30") == "30.06.2026"
    assert estimated_nav_history_display._display_date("ukjent") == "ukjent"


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
    assert (
        by_key["reported_cash"]["formula"]
        == "Siste rapporterte kontantbeholdning (31.03.2026)"
    )
    assert by_key["operating_cost_since_report"]["amount_mnok"] == -7.0
    assert (
        by_key["operating_cost_since_report"]["formula"]
        == "Estimert løpende drift fra 31.03.2026 til 02.04.2026"
    )
    assert by_key["buybacks_since_report"]["amount_mnok"] == -12.0
    assert (
        by_key["buybacks_since_report"]["formula"]
        == "Kontantbruk på egne aksjer etter 31.03.2026"
    )
    assert by_key["other_cash_since_report"]["amount_mnok"] == -3.0
    assert by_key["other_cash_since_report"]["label"] == "Andre kontantbevegelser siden siste rapport"
    assert by_key["other_cash_since_report"]["details"]["confirmed"] is False
    assert by_key["fx_since_report"]["amount_mnok"] == 2.0
    assert by_key["alliance_venture_spring"]["amount_mnok"] == 25.0
    assert by_key["alliance_venture_spring"]["details"]["shares"] == 7_411_532
    assert by_key["alliance_venture_spring"]["details"]["life360_report_shares"] == 37_028
    assert by_key["alliance_venture_spring"]["details"]["display_policy"] == "FIXED_AT_LAST_REPORT"
    assert by_key["other_reported_assets_liabilities"]["amount_mnok"] == 5.0
    assert by_key["life360"]["amount_mnok"] == 50.0
    assert by_key["life360"]["per_share_nok"] == 5.0
    assert by_key["life360"]["formula"] == "37 028 LIF-aksjer × siste LIF-kurs × USD/NOK"
    assert by_key["life360"]["details"]["holding_source_document_id"] == 90
    assert by_key["life360"]["details"]["report_shares"] == 37_028
    assert sum(item["amount_mnok"] for item in current["composition"]) == 150.0
    assert current["composition_split_status"]["ready"] is True
    assert current["composition_split_status"]["anchor_fallback_used"] is False

    drivers = {item["key"]: item for item in result["change"]["drivers"]}
    assert drivers["life360"]["amount_mnok"] == 5.0
    assert drivers["life360"]["per_share_nok"] == 0.5
    assert drivers["life360"]["details"]["start_amount_mnok"] == 45.0
    assert drivers["life360"]["details"]["current_amount_mnok"] == 50.0
    assert drivers["life360"]["label"] == "Life 360"
    assert drivers["life360"]["details"]["start_price_usd"] == 135.0
    assert drivers["life360"]["details"]["current_usd_nok"] == 10.0
    assert (
        drivers["life360"]["details"]["price_effect_mnok"]
        + drivers["life360"]["details"]["fx_effect_mnok"]
        == drivers["life360"]["amount_mnok"]
    )
    assert drivers["other_ona"]["amount_mnok"] == -5.0
    assert drivers["other_ona"]["per_share_nok"] == -0.5
    assert drivers["life360"]["amount_mnok"] + drivers["other_ona"]["amount_mnok"] == 0.0
    assert result["life360_display_policy"] == "GROSS_MARKET_VALUE_WITH_REPORTED_VALUE_FALLBACK"
    assert result["composition_display_policy"] == "REPORT_CASH_ALLIANCE_AND_RESIDUAL_WITH_EXPLICIT_MOVEMENTS_AND_FX"


def test_current_holding_change_does_not_rewrite_report_date_alliance_residual(monkeypatch) -> None:
    base_result = _base_result()
    life_component = next(item for item in base_result["current"]["composition"] if item["key"] == "life360")
    life_component["amount_mnok"] = -3.5
    life_component["per_share_nok"] = -0.35
    ona_component = next(item for item in base_result["current"]["composition"] if item["key"] == "ona")
    ona_component["amount_mnok"] = 83.5
    ona_component["per_share_nok"] = 8.35

    async def base(_repository, *, days):
        assert days == 30
        return base_result

    async def life360(_repository, *, as_of_date):
        if as_of_date == "2026-04-01":
            return _state(market="35000000", embedded="35000000", day=as_of_date)
        return _state(market="31500000", embedded="35000000", day=as_of_date, shares=27_028)

    async def report(_repository, report_date):
        return _report_state(report_shares=37_028)

    monkeypatch.setattr(estimated_nav_history_display, "_estimated_nav_history", base)
    monkeypatch.setattr(estimated_nav_history_display, "life360_nav_adjustment", life360)
    monkeypatch.setattr(estimated_nav_history_display, "_report_split_state", report)
    monkeypatch.setattr(estimated_nav_history_display, "_cash_breakdown", _cash_breakdown)

    result = asyncio.run(estimated_nav_history_display.estimated_nav_history(Repository(), days=30))
    by_key = {item["key"]: item for item in result["current"]["composition"]}
    assert by_key["life360"]["details"]["shares"] == 27_028
    assert by_key["life360"]["details"]["report_shares"] == 37_028
    assert by_key["alliance_venture_spring"]["amount_mnok"] == 25.0
    assert by_key["alliance_venture_spring"]["details"]["life360_report_shares"] == 37_028


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


def test_missing_current_holding_fails_closed_instead_of_using_stale_report_holding(monkeypatch) -> None:
    async def base(_repository, *, days):
        return _base_result()

    async def life360(_repository, *, as_of_date):
        return {
            "ready": False,
            "reason": "missing_current_life360_holding",
            "shares": None,
            "adjustment_nok": Decimal("0"),
        }

    async def report(_repository, report_date):
        return _report_state()

    monkeypatch.setattr(estimated_nav_history_display, "_estimated_nav_history", base)
    monkeypatch.setattr(estimated_nav_history_display, "life360_nav_adjustment", life360)
    monkeypatch.setattr(estimated_nav_history_display, "_report_split_state", report)
    monkeypatch.setattr(estimated_nav_history_display, "_cash_breakdown", _cash_breakdown)

    result = asyncio.run(estimated_nav_history_display.estimated_nav_history(Repository(), days=30))
    assert result["current"]["composition_split_status"]["ready"] is False
    assert result["current"]["composition_split_status"]["reason"] == "missing_current_life360_holding"
    assert result["composition_display_policy"] == "LEGACY_COMPOSITION_FAIL_CLOSED"


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
        if "FROM life360_holding_anchors" in sql:
            assert parameters == ("2026-06-30", "2026-06-30")
            return {
                "id": 3,
                "effective_from": "2025-12-31",
                "effective_to": None,
                "shares": 37_028,
                "quality": "DERIVED_HIGH_CONFIDENCE",
                "basis": "DERIVED_FROM_2025_FAIR_VALUE",
                "source_document_id": 12,
                "source_locator": "Annual Report 2025, Note 4",
                "notes": "derived",
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
    assert result["life360_report_shares"] == 37_028
    assert result["life360_holding_effective_from"] == "2025-12-31"
    assert result["life360_holding_source_document_id"] == 12
    assert result["life360_report_usd"] == Decimal("2049870.08")
    assert result["alliance_report_usd"] == Decimal("1886129.92")
    assert result["residual_report_usd"] == Decimal("-1003000")


def test_year_to_date_is_forwarded_to_estimated_history(monkeypatch) -> None:
    async def base(_repository, *, days, year_to_date):
        assert days == 242
        assert year_to_date is True
        return {"ready": False, "reason": "test_complete"}

    monkeypatch.setattr(
        estimated_nav_history_display, "_estimated_nav_history", base
    )

    result = asyncio.run(
        estimated_nav_history_display.estimated_nav_history(
            Repository(), days=242, year_to_date=True
        )
    )

    assert result["reason"] == "test_complete"
