from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import full_refresh  # noqa: E402
import life360_ir_lseg  # noqa: E402
import life360_market_data  # noqa: E402


class FakeRepository:
    async def first(self, sql, params=()):
        assert "FROM market_prices" in sql
        assert params == ("LIF",)
        return {
            "trading_date": "2026-08-24",
            "observed_at": "2026-08-24T20:00:00Z",
            "price": "45.25",
            "currency": "USD",
            "source_code": "YAHOO_FINANCE",
        }


def test_lif_failure_preserves_yahoo_and_ir_lseg_details(monkeypatch) -> None:
    async def fake_refresh_symbol(repository, *, symbol, target_date, archive_bucket, fetcher):
        if symbol == "LIF":
            raise RuntimeError(
                "Yahoo Finance chart feilet på alle endepunkter: "
                "query1.finance.yahoo.com: Yahoo Finance feilet med HTTP 429; "
                "query2.finance.yahoo.com: Yahoo Finance feilet med HTTP 503"
            )
        return {
            "status": "ok",
            "symbol": symbol,
            "rows_written": 0,
            "history_backfill": False,
        }

    async def fake_ir_fallback(repository, *, target_date, archive_bucket=None, fetcher=None):
        raise RuntimeError("Life360 IR feilet med HTTP 403")

    monkeypatch.setattr(life360_market_data, "_refresh_symbol", fake_refresh_symbol)
    monkeypatch.setattr(life360_ir_lseg, "refresh_life360_ir_lif", fake_ir_fallback)

    result = asyncio.run(
        life360_market_data.refresh_life360_market_data(
            FakeRepository(),
            target_date="2026-08-25",
        )
    )

    assert result["status"] == "error"
    assert result["series"]["LIF"]["error"] == (
        "Life360 LIF kunne ikke oppdateres. Yahoo Finance: "
        "Yahoo Finance chart feilet på alle endepunkter: "
        "query1.finance.yahoo.com: Yahoo Finance feilet med HTTP 429; "
        "query2.finance.yahoo.com: Yahoo Finance feilet med HTTP 503; "
        "Life360 IR/LSEG fallback: RuntimeError: Life360 IR feilet med HTTP 403"
    )
    assert result["last_good_lif"] == {
        "trading_date": "2026-08-24",
        "observed_at": "2026-08-24T20:00:00Z",
        "price": "45.25",
        "currency": "USD",
        "source_code": "YAHOO_FINANCE",
    }


def test_source_health_detail_exposes_lif_failure_and_last_good_price() -> None:
    source_results = {
        "life360": {
            "status": "error",
            "series": {
                "LIF": {
                    "status": "error",
                    "error": (
                        "Life360 LIF kunne ikke oppdateres. Yahoo Finance: "
                        "query1.finance.yahoo.com HTTP 429; "
                        "query2.finance.yahoo.com HTTP 503; "
                        "Life360 IR/LSEG fallback: RuntimeError: HTTP 403"
                    ),
                }
            },
            "last_good_lif": {
                "trading_date": "2026-08-24",
                "price": "45.25",
                "currency": "USD",
                "source_code": "YAHOO_FINANCE",
            },
        }
    }

    detail = full_refresh._source_group_detail(
        "YAHOO_FINANCE",
        source_results,
        {"life360": "DOWN"},
    )

    assert detail == (
        "LIF: Life360 LIF kunne ikke oppdateres. Yahoo Finance: "
        "query1.finance.yahoo.com HTTP 429; query2.finance.yahoo.com HTTP 503; "
        "Life360 IR/LSEG fallback: RuntimeError: HTTP 403; "
        "Siste gode LIF-kurs: 45.25 USD (2026-08-24, YAHOO_FINANCE)"
    )
