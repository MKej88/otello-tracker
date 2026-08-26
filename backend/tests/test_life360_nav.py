from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from life360_nav import life360_nav_adjustment  # noqa: E402


class _Repository:
    def __init__(self, *, current_shares: int = 37_028, missing_current_holding: bool = False):
        self.current_shares = current_shares
        self.missing_current_holding = missing_current_holding

    async def first(self, sql: str, parameters=()):
        if "FROM other_net_assets_reported_anchors" in sql:
            return {"as_of_date": "2025-12-31"}
        if "FROM life360_holding_anchors" in sql:
            day = str(parameters[0])
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
            day = str(parameters[0])
            if day == "2025-12-31":
                return {
                    "trading_date": "2025-12-31",
                    "observed_at": "2025-12-31T21:00:00Z",
                    "price": "64.14",
                    "quality": "SECONDARY",
                    "source_document_id": 10,
                    "source_code": "YAHOO_FINANCE",
                }
            return {
                "trading_date": "2026-08-21",
                "observed_at": "2026-08-21T20:00:01Z",
                "price": "44.66",
                "quality": "SECONDARY",
                "source_document_id": 11,
                "source_code": "YAHOO_FINANCE",
            }
        if "FROM fx_rates" in sql:
            return {
                "rate_date": "2026-08-21",
                "rate": "10.0",
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


def test_life360_does_not_restate_pre_fair_value_history() -> None:
    result = asyncio.run(life360_nav_adjustment(_Repository(), as_of_date="2025-06-30"))
    assert result["ready"] is False
    assert result["reason"] == "life360_fair_value_policy_not_active"
    assert result["adjustment_nok"] == Decimal("0")
    assert result["history_available_from"] == "2019-05-10"
