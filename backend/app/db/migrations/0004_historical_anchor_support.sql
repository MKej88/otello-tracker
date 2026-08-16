-- Preserve report-native currencies for historical cash anchors.
ALTER TABLE cash_anchors RENAME TO cash_anchors_v1;

CREATE TABLE cash_anchors (
    id INTEGER PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    amount_nok TEXT,
    reported_amount TEXT,
    reported_currency TEXT,
    fx_rate_to_nok TEXT,
    anchor_type TEXT NOT NULL DEFAULT 'REPORTED' CHECK (anchor_type IN ('REPORTED', 'MANUAL_ADJUSTMENT')),
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        amount_nok IS NOT NULL
        OR (reported_amount IS NOT NULL AND reported_currency IS NOT NULL)
    ),
    UNIQUE (as_of_date, anchor_type, source_document_id)
);

INSERT INTO cash_anchors(
    id, as_of_date, amount_nok, reported_amount, reported_currency,
    fx_rate_to_nok, anchor_type, source_document_id, notes, created_at
)
SELECT
    id, as_of_date, amount_nok, amount_nok, 'NOK', '1', anchor_type,
    source_document_id, notes, created_at
FROM cash_anchors_v1;

DROP TABLE cash_anchors_v1;
CREATE INDEX idx_cash_anchors_date ON cash_anchors(as_of_date);

-- Corporate actions such as share cancellations need an exact quantity.
ALTER TABLE corporate_actions
    ADD COLUMN quantity INTEGER CHECK (quantity IS NULL OR quantity >= 0);
