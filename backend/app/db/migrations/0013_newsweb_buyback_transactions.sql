INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes)
VALUES (
    'NEWSWEB',
    'Oslo Børs NewsWeb',
    'EXCHANGE',
    'https://newsweb.oslobors.no/',
    1,
    1,
    'Official Oslo Børs disclosure and attachment source. Store only OTEC-relevant facts/metadata needed for private research and provenance.'
)
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    source_type = excluded.source_type,
    base_url = excluded.base_url,
    is_official = excluded.is_official,
    is_active = excluded.is_active,
    terms_notes = excluded.terms_notes;

CREATE TABLE buyback_daily_transactions (
    id INTEGER PRIMARY KEY,
    weekly_buyback_id INTEGER NOT NULL REFERENCES buybacks(id) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    shares INTEGER NOT NULL CHECK(shares > 0),
    avg_price_nok TEXT NOT NULL,
    amount_nok TEXT NOT NULL,
    trade_count INTEGER NOT NULL CHECK(trade_count > 0),
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    quality TEXT NOT NULL DEFAULT 'CONFIRMED'
        CHECK(quality IN ('CONFIRMED', 'RECONCILED', 'REQUIRES_REVIEW')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(weekly_buyback_id, trade_date)
);

CREATE INDEX idx_buyback_daily_transactions_date
    ON buyback_daily_transactions(trade_date);
CREATE INDEX idx_buyback_daily_transactions_weekly
    ON buyback_daily_transactions(weekly_buyback_id, trade_date);

-- SQLite cannot extend the original movement_type CHECK in place. Rebuild the table once
-- so daily attachment-derived buyback cash can coexist with the weekly audit summary.
CREATE TABLE cash_movements_v13 (
    id INTEGER PRIMARY KEY,
    movement_date TEXT NOT NULL,
    movement_type TEXT NOT NULL CHECK (movement_type IN (
        'BEMOBI_DIVIDEND', 'BEMOBI_JCP', 'OTELLO_BUYBACK', 'OTELLO_BUYBACK_DAILY',
        'OTELLO_DISTRIBUTION', 'OPEX', 'TAX', 'FX', 'OTHER'
    )),
    amount_nok TEXT NOT NULL,
    amount_original TEXT,
    currency TEXT NOT NULL DEFAULT 'NOK',
    fx_rate_to_nok TEXT,
    description TEXT NOT NULL,
    source_document_id INTEGER REFERENCES source_documents(id),
    confidence TEXT NOT NULL DEFAULT 'CONFIRMED'
        CHECK (confidence IN ('CONFIRMED', 'ESTIMATED', 'MANUAL')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    corporate_action_id INTEGER REFERENCES corporate_actions(id),
    buyback_id INTEGER REFERENCES buybacks(id)
);

INSERT INTO cash_movements_v13(
    id, movement_date, movement_type, amount_nok, amount_original, currency,
    fx_rate_to_nok, description, source_document_id, confidence, created_at,
    corporate_action_id, buyback_id
)
SELECT
    id, movement_date, movement_type, amount_nok, amount_original, currency,
    fx_rate_to_nok, description, source_document_id, confidence, created_at,
    corporate_action_id, NULL
FROM cash_movements;

DROP TABLE cash_movements;
ALTER TABLE cash_movements_v13 RENAME TO cash_movements;

CREATE INDEX idx_cash_movements_date ON cash_movements(movement_date);
CREATE INDEX idx_cash_movements_type ON cash_movements(movement_type);
CREATE INDEX idx_cash_movements_buyback_id ON cash_movements(buyback_id);
CREATE UNIQUE INDEX idx_cash_movements_corporate_action
    ON cash_movements(corporate_action_id)
    WHERE corporate_action_id IS NOT NULL;

-- Existing weekly rows predate the explicit buyback foreign key. Otello has at most one
-- weekly status row per period-end date in the curated history, so the date is a stable
-- migration key. New writes set buyback_id directly in the NewsWeb sync layer.
UPDATE cash_movements
SET buyback_id = (
    SELECT b.id
    FROM buybacks b
    WHERE b.trade_date = cash_movements.movement_date
    ORDER BY b.id
    LIMIT 1
)
WHERE movement_type = 'OTELLO_BUYBACK'
  AND buyback_id IS NULL;
