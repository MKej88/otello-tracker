from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import upsert_market_price
from app.marketdata.quote_details import (
    _nasdaq_close_timestamp,
    _normalize_lif_yahoo_price,
    market_quote_details,
)

ROOT = Path(__file__).resolve().parents[2]


def _load_worker_quote_details():
    path = ROOT / "cloudflare/src/quote_details.py"
    spec = importlib.util.spec_from_file_location("worker_lif_quotes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_yahoo_lif_price(
    database: str, *, trading_date: str, retrieved_at: str
) -> None:
    with get_connection(database) as connection:
        source_id = connection.execute(
            "SELECT id FROM sources WHERE code='YAHOO_FINANCE'"
        ).fetchone()["id"]
        cursor = connection.execute(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, url, fetched_at
            ) VALUES (?, ?, 'API_RESPONSE', 'Yahoo LIF test',
                      'https://query.example.test/LIF', ?)
            """,
            (source_id, f"lif-{trading_date}-{retrieved_at}", retrieved_at),
        )
        upsert_market_price(
            connection,
            symbol="LIF",
            observed_at=f"{trading_date}T13:30:00Z",
            trading_date=trading_date,
            price_type="CLOSE",
            price="45.50",
            currency="USD",
            source_code="YAHOO_FINANCE",
            source_document_id=cursor.lastrowid,
            quality="DIRECT",
        )
        connection.commit()


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
    assert life360["range_52w"]["low"] <= 44.1
    assert life360["range_52w"]["high"] >= 45.5
    assert life360["range_52w"]["basis"] == "DAILY_CLOSE"


def test_life360_er_eksponert_i_worker_og_frontend() -> None:
    worker = (ROOT / "cloudflare/src/quote_details.py").read_text(encoding="utf-8")
    panel = (ROOT / "frontend/src/MarketQuotePanel.tsx").read_text(encoding="utf-8")

    assert '"LIF": {"currency": "USD", "source": "YAHOO_FINANCE"}' in worker
    assert "data?.symbols?.LIF" in panel
    assert 'title="Life360 / LIF"' in panel
    assert 'currency === "USD"' in panel


def test_life360_intradag_bruker_faktisk_innhentingstid(tmp_path) -> None:
    database = str(tmp_path / "life360-intraday.db")
    init_database(database)
    _seed_yahoo_lif_price(
        database,
        trading_date="2026-08-31",
        retrieved_at="2026-08-31T18:00:00Z",
    )

    life360 = market_quote_details(database)["symbols"]["LIF"]

    assert life360["last_price_type"] == "LAST"
    assert life360["last_updated_at"] == "2026-08-31T18:00:00Z"


@pytest.mark.parametrize(
    ("trading_date", "retrieved_at", "expected_close"),
    [
        ("2026-08-31", "2026-08-31T20:01:00Z", "2026-08-31T20:00:00Z"),
        ("2026-12-01", "2026-12-01T21:01:00Z", "2026-12-01T21:00:00Z"),
    ],
)
def test_life360_fullfort_dag_bruker_nasdaq_stengetid(
    tmp_path, trading_date: str, retrieved_at: str, expected_close: str
) -> None:
    database = str(tmp_path / f"life360-close-{trading_date}.db")
    init_database(database)
    _seed_yahoo_lif_price(
        database,
        trading_date=trading_date,
        retrieved_at=retrieved_at,
    )

    life360 = market_quote_details(database)["symbols"]["LIF"]

    assert life360["last_price_type"] == "CLOSE"
    assert life360["last_updated_at"] == expected_close


def test_worker_og_referanse_har_lik_life360_semantikk() -> None:
    worker = _load_worker_quote_details()
    rows = [
        {
            "trading_date": "2026-08-31",
            "source_code": "YAHOO_FINANCE",
            "source_retrieved_at": "2026-08-31T18:00:00Z",
            "price_type": "CLOSE",
            "observed_at": "2026-08-31T13:30:00Z",
        },
        {
            "trading_date": "2026-12-01",
            "source_code": "YAHOO_FINANCE",
            "source_retrieved_at": "2026-12-01T21:01:00Z",
            "price_type": "CLOSE",
            "observed_at": "2026-12-01T14:30:00Z",
        },
    ]

    for row in rows:
        assert worker._normalize_lif_yahoo_price(row) == _normalize_lif_yahoo_price(row)
    assert worker._nasdaq_close_timestamp("2026-08-31") == _nasdaq_close_timestamp(
        "2026-08-31"
    )


def test_life360_beholdes_i_eksisterende_30_minutters_refresh() -> None:
    wrangler = (ROOT / "cloudflare/wrangler.jsonc").read_text(encoding="utf-8")
    scheduled = (ROOT / "cloudflare/src/scheduled.py").read_text(encoding="utf-8")

    assert '"crons": ["*/30 * * * *"]' in wrangler
    assert "repair_life360_lif_if_stale" in scheduled
    assert "force_refresh=True" in scheduled
