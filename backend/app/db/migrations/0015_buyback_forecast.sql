ALTER TABLE buyback_programs ADD COLUMN max_price_nok TEXT;
ALTER TABLE buybacks ADD COLUMN period_start TEXT;

CREATE INDEX idx_buybacks_period_start ON buybacks(period_start);

CREATE TABLE market_activity (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    trading_date TEXT NOT NULL,
    volume_shares INTEGER NOT NULL CHECK (volume_shares >= 0),
    last_price_nok TEXT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    source_document_id INTEGER REFERENCES source_documents(id),
    quality TEXT NOT NULL CHECK (quality IN ('HISTORICAL_EXPORT', 'DELAYED_TRADE_SUM')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (instrument_id, trading_date, source_id)
);

CREATE INDEX idx_market_activity_instrument_date
    ON market_activity(instrument_id, trading_date);
