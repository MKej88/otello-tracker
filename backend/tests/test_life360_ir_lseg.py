from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from life360_ir_lseg import (  # noqa: E402
    LIFE360_IR_HISTORY_URL,
    MAX_FALLBACK_AGE_DAYS,
    parse_life360_ir_history,
    refresh_life360_ir_lif,
    select_fresh_close,
)


HTML = b"""
<html><body>
<table>
  <tr><th>Date Requested</th><th>Open</th><th>High</th><th>Low</th><th>Closing Price</th><th>Volume</th></tr>
  <tr><td>August 21, 2026</td><td>$44.10</td><td>$45.00</td><td>$43.90</td><td>$44.66</td><td>1,000</td></tr>
  <tr><td>August 24, 2026</td><td>$44.70</td><td>$46.00</td><td>$44.50</td><td>$45.25</td><td>2,000</td></tr>
</table>
<p>Data provided by LSEG. Minimum 15 minutes delayed.</p>
</body></html>
"""


class FakeResponse:
    def __init__(self, payload: bytes = HTML, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.ok = 200 <= status < 300
        self.headers = {"content-length": str(len(payload))}

    async def text(self):
        return self.payload.decode("utf-8")


class FakeRepository:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.runs: list[tuple[str, tuple]] = []

    async def create_source_document(self, **kwargs):
        self.documents.append(kwargs)
        return 91

    async def source_id(self, code: str):
        assert code == "LIFE360_IR_LSEG"
        return 7

    async def instrument_id(self, symbol: str):
        assert symbol == "LIF"
        return 8

    async def run(self, sql: str, parameters=()):
        self.runs.append((sql, tuple(parameters)))
        return None


def test_parser_reads_closing_prices_from_ir_table() -> None:
    rows = parse_life360_ir_history(HTML)
    assert rows == [
        {
            "trading_date": "2026-08-21",
            "observed_at": "2026-08-21T23:59:59Z",
            "price": "44.66",
        },
        {
            "trading_date": "2026-08-24",
            "observed_at": "2026-08-24T23:59:59Z",
            "price": "45.25",
        },
    ]


def test_select_fresh_close_uses_latest_row_not_after_target() -> None:
    rows = parse_life360_ir_history(HTML)
    selected = select_fresh_close(rows, target_date="2026-08-23")
    assert selected["trading_date"] == "2026-08-21"
    assert selected["price"] == "44.66"


def test_select_fresh_close_rejects_stale_price() -> None:
    rows = parse_life360_ir_history(HTML)
    with pytest.raises(ValueError, match="maks"):
        select_fresh_close(
            rows,
            target_date=f"2026-09-{1 + MAX_FALLBACK_AGE_DAYS:02d}",
        )


def test_parser_fails_closed_without_expected_columns() -> None:
    with pytest.raises(ValueError, match="Closing Price"):
        parse_life360_ir_history("<table><tr><th>Date</th><th>Value</th></tr></table>")


def test_refresh_uses_only_fixed_life360_ir_url_and_persists_lif_close() -> None:
    repository = FakeRepository()
    calls: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        calls.append(url)
        return FakeResponse()

    result = asyncio.run(
        refresh_life360_ir_lif(
            repository,
            target_date="2026-08-25",
            fetcher=fake_fetch,
        )
    )

    assert calls == [LIFE360_IR_HISTORY_URL]
    assert result["status"] == "ok"
    assert result["source_code"] == "LIFE360_IR_LSEG"
    assert result["price_date"] == "2026-08-24"
    assert result["price"] == "45.25"
    assert result["fallback_only"] is True
    assert result["history_complete"] is False
    assert repository.documents[0]["url"] == LIFE360_IR_HISTORY_URL
    assert "LSEG" in repository.documents[0]["title"]
    assert len(repository.runs) == 1
    assert "'DIRECT'" in repository.runs[0][0]
