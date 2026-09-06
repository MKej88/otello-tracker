import sqlite3

import pytest

from app.marketdata.quote_details import _latest_price


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE instruments (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL);
        CREATE TABLE sources (id INTEGER PRIMARY KEY, code TEXT NOT NULL);
        CREATE TABLE source_documents (id INTEGER PRIMARY KEY, fetched_at TEXT);
        CREATE TABLE market_prices (
            id INTEGER PRIMARY KEY,
            instrument_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            source_document_id INTEGER,
            trading_date TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            price_type TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT,
            quality TEXT,
            metadata_json TEXT
        );
        INSERT INTO instruments (id, symbol) VALUES (1, 'OTEC');
        INSERT INTO sources (id, code) VALUES (1, 'EURONEXT');
        INSERT INTO market_prices (
            id, instrument_id, source_id, trading_date, observed_at,
            price_type, price, currency, quality, metadata_json
        ) VALUES
            (1, 1, 1, '2026-09-04', '2026-09-04T14:00:00+00:00',
             'CLOSE', 17.84, 'NOK', 'DIRECT', '{}'),
            (2, 1, 1, '2026-09-04', '2026-09-04T14:15:00+00:00',
             'LAST', 17.98, 'NOK', 'DIRECT', '{}');
        """
    )
    return connection


def test_otec_same_day_last_trade_beats_stale_close() -> None:
    connection = _connection()

    latest = _latest_price(connection, "OTEC")

    assert latest is not None
    assert latest["price_type"] == "LAST"
    assert latest["price"] == pytest.approx(17.98)
