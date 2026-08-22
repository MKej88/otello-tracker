from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from life360_nav import LIFE360_COMMON_SHARES, life360_nav_adjustment  # noqa: E402


class _Repository:
    async def first(self, sql: str, parameters=()):
        if "FROM other_net_assets_reported_anchors" in sql:
            return {"as_of_date": "2025-12-31"}
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

    expected = Decimal(LIFE360_COMMON_SHARES) * (Decimal("44.66") - Decimal("64.14")) * Decimal("10")
    assert LIFE360_COMMON_SHARES == 37_028
    assert result["ready"] is True
    assert result["anchor_date"] == "2025-12-31"
    assert result["price"] == Decimal("44.66")
    assert result["anchor_price_usd"] == Decimal("64.14")
    assert result["adjustment_nok"] == expected
    assert result["market_value_nok"] == Decimal(37_028) * Decimal("44.66") * Decimal("10")
    assert result["method"] == "CURRENT_LIF_MINUS_REPORTED_LIF_FAIR_VALUE_IN_CARRIED_USD_ONA"


def test_life360_does_not_restate_pre_fair_value_history() -> None:
    result = asyncio.run(life360_nav_adjustment(_Repository(), as_of_date="2025-06-30"))
    assert result["ready"] is False
    assert result["reason"] == "life360_fair_value_policy_not_active"
    assert result["adjustment_nok"] == Decimal("0")
    assert result["history_available_from"] == "2019-05-10"
