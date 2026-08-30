from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from life360_nav import life360_market_value, life360_nav_adjustment  # noqa: E402


class _Repository:
    def __init__(
        self,
        *,
        current_shares: int = 37_028,
        missing_current_holding: bool = False,
        missing_current_price: bool = False,
    ):
        self.current_shares = current_shares
        self.missing_current_holding = missing_current_holding
        self.missing_current_price = missing_current_price

    async def first(self, sql: str, parameters=()):
        if "FROM other_net_assets_reported_anchors" in sql:
            return {"as_of_date": "2025-12-31"}
        if "FROM life360_holding_anchors" in sql:
            day = str(parameters[0])
            if day < "2025-12-31":
                return {
                    "id": 2,
                    "effective_from": "2022-12-31",
                    "effective_to": "2025-12-30",
                    "shares": 37_028,
                    "quality": "DERIVED_MEDIUM_CONFIDENCE",
                    "basis": "CONTINUITY_DERIVED_FROM_REPORTED_OWNERSHIP_AND_2025_FAIR_VALUE",
                    "source_document_id": 19,
                    "source_locator": "Annual Report 2024 continuity attribution",
                    "notes": "historical attribution test",
                }
            if day == "2025-12-31":
                shares = 37_028
                effective_from = "2025-12-31"
                source_document_id = 20
            else:
                if self.missing_current_holding:
                    return None
                shares = self.current_shares
                effective_from = "2026-07-01" if shares != 37_028 else "2025-12-31"
                source_document_id = 21 if shares != 37_028 else 20
            return {
                "id": 1,
                "effective_from": effective_from,
                "effective_to": None,
                "shares": shares,
                "quality": "DERIVED_HIGH_CONFIDENCE",
                "basis": "DERIVED_FROM_2025_FAIR_VALUE",
                "source_document_id": source_document_id,
                "source_locator": "Annual Report 2025, Note 4",
                "notes": "test",
            }
        if "FROM market_prices" in sql:
            symbol, currency, day = map(str, parameters[:3])
            if symbol == "360.AX":
                return {
                    "trading_date": day,
                    "observed_at": f"{day}T06:00:00Z",
                    "price": "20.00",
                    "quality": "SECONDARY",
                    "source_document_id": 9,
                    "source_code": "YAHOO_FINANCE",
                }
            assert symbol == "LIF"
            assert currency == "USD"
            if day == "2025-12-31":
                return {
                    "trading_date": "2025-12-31",
                    "observed_at": "2025-12-31T21:00:00Z",
                    "price": "64.14",
                    "quality": "SECONDARY",
                    "source_document_id": 10,
                    "source_code": "YAHOO_FINANCE",
                }
            if self.missing_current_price and day >= "2026-01-01":
                return None
            return {
                "trading_date": day,
                "observed_at": f"{day}T20:00:01Z",
                "price": "44.66",
                "quality": "SECONDARY",
                "source_document_id": 11,
                "source_code": "YAHOO_FINANCE",
            }
        if "FROM fx_rates" in sql:
            base_currency, day = map(str, parameters[:2])
            return {
                "rate_date": day,
                "rate": "6.5" if base_currency == "AUD" else "10.0",
                "source_document_id": 12,
                "source_code": "NORGES_BANK",
            }
        raise AssertionError(sql)


def test_life360_adjustment_replaces_embedded_fair_value_without_double_counting() -> None:
    result = asyncio.run(life360_nav_adjustment(_Repository(), as_of_date="2026-08-21"))

    expected = Decimal(37_028) * (Decimal("44.66") - Decimal("64.14")) * Decimal("10")
    assert result["ready"] is True
    assert result["shares"] == 37_028
    assert result["anchor_shares"] == 37_028
    assert result["holding_effective_from"] == "2025-12-31"
    assert result["holding_source_document_id"] == 20
    assert result["anchor_date"] == "2025-12-31"
    assert result["price"] == Decimal("44.66")
    assert result["anchor_price_usd"] == Decimal("64.14")
    assert result["adjustment_nok"] == expected
    assert result["market_value_nok"] == Decimal(37_028) * Decimal("44.66") * Decimal("10")
    assert result["method"] == "CURRENT_LIF_MINUS_REPORTED_LIF_FAIR_VALUE_IN_CARRIED_USD_ONA"


def test_life360_uses_current_holding_and_report_date_holding_independently() -> None:
    result = asyncio.run(
        life360_nav_adjustment(_Repository(current_shares=27_028), as_of_date="2026-08-21")
    )

    expected = (
        Decimal(27_028) * Decimal("44.66")
        - Decimal(37_028) * Decimal("64.14")
    ) * Decimal("10")
    assert result["ready"] is True
    assert result["shares"] == 27_028
    assert result["anchor_shares"] == 37_028
    assert result["holding_effective_from"] == "2026-07-01"
    assert result["anchor_holding_effective_from"] == "2025-12-31"
    assert result["adjustment_nok"] == expected
    assert result["market_value_nok"] == Decimal(27_028) * Decimal("44.66") * Decimal("10")
    assert result["embedded_value_nok"] == Decimal(37_028) * Decimal("64.14") * Decimal("10")


def test_life360_fails_closed_when_current_holding_is_missing() -> None:
    result = asyncio.run(
        life360_nav_adjustment(
            _Repository(missing_current_holding=True),
            as_of_date="2026-08-21",
        )
    )
    assert result["ready"] is False
    assert "current_life360_holding" in result["reason"]
    assert result["adjustment_nok"] == Decimal("0")


def test_life360_preserves_holding_provenance_when_current_price_is_missing() -> None:
    result = asyncio.run(
        life360_nav_adjustment(
            _Repository(missing_current_price=True),
            as_of_date="2026-08-21",
        )
    )

    assert result["ready"] is False
    assert result["reason"] == "missing_current_lif_price"
    assert result["shares"] == 37_028
    assert result["holding_effective_from"] == "2025-12-31"
    assert result["holding_quality"] == "DERIVED_HIGH_CONFIDENCE"
    assert result["holding_basis"] == "DERIVED_FROM_2025_FAIR_VALUE"
    assert result["holding_source_document_id"] == 20
    assert result["holding_source_locator"] == "Annual Report 2025, Note 4"
    assert result["anchor_shares"] == 37_028
    assert result["anchor_holding_effective_from"] == "2025-12-31"
    assert result["anchor_holding_quality"] == "DERIVED_HIGH_CONFIDENCE"
    assert result["anchor_holding_basis"] == "DERIVED_FROM_2025_FAIR_VALUE"
    assert result["anchor_holding_source_document_id"] == 20
    assert result["adjustment_nok"] == Decimal("0")


def test_life360_does_not_restate_pre_fair_value_history() -> None:
    result = asyncio.run(life360_nav_adjustment(_Repository(), as_of_date="2025-06-30"))
    assert result["ready"] is False
    assert result["reason"] == "life360_fair_value_policy_not_active"
    assert result["adjustment_nok"] == Decimal("0")
    assert result["history_available_from"] == "2019-05-10"


def test_historical_life360_uses_three_asx_cdis_per_common_share() -> None:
    result = asyncio.run(life360_market_value(_Repository(), as_of_date="2023-08-30"))

    expected = Decimal(37_028) * Decimal("3") * Decimal("20") * Decimal("6.5")
    assert result["ready"] is True
    assert result["market_symbol"] == "360.AX"
    assert result["currency"] == "AUD"
    assert result["quote_units_per_common"] == Decimal("3")
    assert result["holding_quality"] == "DERIVED_MEDIUM_CONFIDENCE"
    assert result["market_value_nok"] == expected
    assert result["method"] == "ASX_CDI_3_TO_1_TIMES_AUD_NOK"
    assert result["accounting_nav_restatement"] is False


def test_historical_life360_switches_to_nasdaq_common_shares_from_listing() -> None:
    result = asyncio.run(life360_market_value(_Repository(), as_of_date="2025-06-30"))

    expected = Decimal(37_028) * Decimal("44.66") * Decimal("10")
    assert result["ready"] is True
    assert result["market_symbol"] == "LIF"
    assert result["currency"] == "USD"
    assert result["quote_units_per_common"] == Decimal("1")
    assert result["market_value_nok"] == expected
    assert result["method"] == "NASDAQ_COMMON_TIMES_USD_NOK"
    assert result["accounting_nav_restatement"] is False
