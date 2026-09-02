-- Identifiser kildebelagte patentbetalinger eksplisitt uten å endre beløpene.
CREATE TABLE cash_movements_patent (
    id INTEGER PRIMARY KEY,
    movement_date TEXT NOT NULL,
    movement_type TEXT NOT NULL CHECK (movement_type IN (
        'BEMOBI_DIVIDEND', 'BEMOBI_JCP', 'OTELLO_BUYBACK', 'OTELLO_BUYBACK_DAILY',
        'OTELLO_DISTRIBUTION', 'PATENT_PROCEEDS', 'OPEX', 'TAX', 'FX', 'OTHER'
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
    buyback_id INTEGER REFERENCES buybacks(id),
    external_movement_id TEXT
);

INSERT INTO cash_movements_patent(
    id, movement_date, movement_type, amount_nok, amount_original, currency,
    fx_rate_to_nok, description, source_document_id, confidence, created_at,
    corporate_action_id, buyback_id, external_movement_id
)
SELECT id, movement_date,
       CASE WHEN external_movement_id LIKE
           'otello-report-post-cash:PATENT_SALE_FINAL_INSTALMENT:%'
           THEN 'PATENT_PROCEEDS' ELSE movement_type END,
       amount_nok, amount_original, currency, fx_rate_to_nok, description,
       source_document_id, confidence, created_at, corporate_action_id, buyback_id,
       external_movement_id
FROM cash_movements;

DROP TABLE cash_movements;
ALTER TABLE cash_movements_patent RENAME TO cash_movements;

CREATE INDEX idx_cash_movements_date ON cash_movements(movement_date);
CREATE INDEX idx_cash_movements_type ON cash_movements(movement_type);
CREATE INDEX idx_cash_movements_buyback_id ON cash_movements(buyback_id);
CREATE UNIQUE INDEX idx_cash_movements_corporate_action
    ON cash_movements(corporate_action_id) WHERE corporate_action_id IS NOT NULL;
CREATE UNIQUE INDEX idx_cash_movements_external_movement_id
    ON cash_movements(external_movement_id) WHERE external_movement_id IS NOT NULL;

CREATE TRIGGER prevent_weekly_buyback_cash_when_daily
BEFORE INSERT ON cash_movements
WHEN NEW.movement_type = 'OTELLO_BUYBACK'
 AND EXISTS (
     SELECT 1 FROM buybacks b
     JOIN buyback_daily_transactions d ON d.weekly_buyback_id = b.id
     WHERE b.trade_date = NEW.movement_date
 )
BEGIN
    SELECT RAISE(IGNORE);
END;
