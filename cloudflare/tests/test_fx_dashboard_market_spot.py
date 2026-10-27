"""The BRL/NOK spot quote is distinct from official historical FX fixes."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from src.fx_dashboard import fx_dashboard


class FXRepository:
    async def first(self, sql: str, parameters=()):
        assert "MAX(substr" in sql
        assert "s.code IN ('NORGES_BANK', 'ECB')" in sql
        return {"max_date": "2026-10-26"}

    async def all(self, sql: str, parameters=()):
        assert "s.code IN ('NORGES_BANK', 'ECB')" in sql
        base = parameters[0]
        if base == "BRL":
            return [
                {"rate_date": "2026-10-23", "rate": "1.853", "source_code": "NORGES_BANK"},
                {"rate_date": "2026-10-26", "rate": "1.6721", "source_code": "NORGES_BANK"},
            ]
        return [
            {"rate_date": "2026-10-23", "rate": "9.3509", "source_code": "NORGES_BANK"},
            {"rate_date": "2026-10-26", "rate": "9.3444", "source_code": "NORGES_BANK"},
        ]


def test_fx_page_shows_validated_exr_spot_not_norges_bank_fix() -> None:
    quote = {
        "rate": "1.7328", "source_code": "EXCHANGERATE_DEV",
        "observed_at": "2026-10-26T18:00:00Z",
        "age_minutes": 690, "carried_forward": True,
    }
    with patch("src.fx_dashboard.latest_indicative_brl_nok", new=AsyncMock(return_value=quote)):
        result = asyncio.run(fx_dashboard(FXRepository()))
    assert result["ready"]
    assert result["current"]["brl_nok"] == 1.7328
    assert result["current"]["source"] == "EXCHANGERATE_DEV"
    assert result["current"]["carried_forward"] is True
    assert result["current"]["observed_at"] == quote["observed_at"]
    assert result["series"][-1]["brl_nok"] == 1.6721
    assert result["as_of_date"] == "2026-10-26"
    assert any(src["code"] == "EXCHANGERATE_DEV" for src in result["sources"])


def test_fx_page_falls_back_to_official_rate_without_recent_market_observation() -> None:
    with patch("src.fx_dashboard.latest_indicative_brl_nok", new=AsyncMock(return_value=None)):
        result = asyncio.run(fx_dashboard(FXRepository()))
    assert result["current"]["brl_nok"] == 1.6721
    assert result["current"]["source"] == "NORGES_BANK"
    assert result["current"]["observed_at"] is None
