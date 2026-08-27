from __future__ import annotations

from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import upsert_market_price
from app.marketdata.quote_details import market_quote_details


ROOT = Path(__file__).resolve().parents[2]


def test_life360_er_med_i_kurser_og_handelsdata(tmp_path) -> None:
    database = str(tmp_path / "life360-quote.db")
    init_database(database)

    with get_connection(database) as connection:
        for day, close in (
            ("2026-08-25", "44.10"),
            ("2026-08-26", "45.50"),
        ):
            upsert_market_price(
                connection,
                symbol="LIF",
                observed_at=f"{day}T20:00:00Z",
                trading_date=day,
                price_type="CLOSE",
                price=close,
                currency="USD",
                source_code="YAHOO_FINANCE",
                quality="DIRECT",
            )
        connection.commit()

    payload = market_quote_details(database)
    life360 = payload["symbols"]["LIF"]

    assert life360["ready"] is True
    assert life360["currency"] == "USD"
    assert life360["source"] == "YAHOO_FINANCE"
    assert life360["last"] == 45.5
    assert life360["last_close"]["price"] == 45.5
    assert life360["session"] == {
        "open": None,
        "low": None,
        "high": None,
        "basis": "CLOSE_ONLY",
    }
    assert life360["volume"]["latest"] is None
    assert life360["volume"]["average_sessions"] == 0
    assert life360["range_52w"]["low"] == 44.1
    assert life360["range_52w"]["high"] == 45.5
    assert life360["range_52w"]["basis"] == "DAILY_CLOSE"


def test_life360_er_eksponert_i_worker_og_frontend() -> None:
    worker = (ROOT / "cloudflare/src/quote_details.py").read_text(encoding="utf-8")
    panel = (ROOT / "frontend/src/MarketQuotePanel.tsx").read_text(encoding="utf-8")

    assert '"LIF": {"currency": "USD", "source": "YAHOO_FINANCE"}' in worker
    assert 'data?.symbols?.LIF' in panel
    assert 'title="Life360 / LIF"' in panel
    assert 'currency === "USD"' in panel
