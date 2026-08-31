from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from quote_details import _volume_stats  # noqa: E402


class _UnusedRepository:
    async def all(self, *_args, **_kwargs):
        raise AssertionError("BMOB3-volum skal ikke kreve ekstra databasekall")


def test_bmob3_yahoo_intraday_volume_overrides_latest_but_not_completed_average() -> None:
    history = [
        {
            "trading_date": "2026-08-27",
            "metadata_json": json.dumps({"quantity_shares": 300_000}),
        },
        {
            "trading_date": "2026-08-28",
            "metadata_json": json.dumps({"quantity_shares": 400_000}),
        },
    ]
    latest = {
        "trading_date": "2026-08-31",
        "metadata_json": json.dumps(
            {
                "volume_shares": 425_000,
                "volume_source": "YAHOO_FINANCE",
                "volume_basis": "YAHOO_REGULAR_MARKET_VOLUME",
                "volume_provisional": True,
            }
        ),
    }

    result = asyncio.run(
        _volume_stats(_UnusedRepository(), "BMOB3", history, latest)
    )

    assert result["latest"] == 425_000
    assert result["latest_date"] == "2026-08-31"
    assert result["source"] == "YAHOO_FINANCE"
    assert result["basis"] == "YAHOO_FINANCE_INTRADAY"
    assert result["provisional"] is True
    assert result["average_3m"] == 350_000
    assert result["average_sessions"] == 2
    assert result["latest_above_average"] is True


def test_bmob3_completed_volume_remains_official_cotahist() -> None:
    history = [
        {
            "trading_date": "2026-08-28",
            "metadata_json": json.dumps({"quantity_shares": 431_500}),
        }
    ]
    latest = {
        "trading_date": "2026-08-28",
        "metadata_json": json.dumps({"quantity_shares": 431_500}),
    }

    result = asyncio.run(
        _volume_stats(_UnusedRepository(), "BMOB3", history, latest)
    )

    assert result["latest"] == 431_500
    assert result["latest_date"] == "2026-08-28"
    assert result["source"] == "B3"
    assert result["basis"] == "B3_COTAHIST_QUANTITY"
    assert result["provisional"] is False
