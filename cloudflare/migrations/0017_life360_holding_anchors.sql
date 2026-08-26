-- Source-backed, effective-dated Life360 holdings used by investor NAV.
CREATE TABLE life360_holding_anchors (
    id INTEGER PRIMARY KEY,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    shares INTEGER NOT NULL CHECK (shares >= 0),
    quality TEXT NOT NULL,
    basis TEXT NOT NULL,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    source_locator TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (effective_to IS NULL OR effective_to >= effective_from),
    UNIQUE (effective_from)
);

CREATE INDEX idx_life360_holding_effective
    ON life360_holding_anchors(effective_from, effective_to);

-- Existing production D1 already has the curated Annual Report 2025 source document.
-- Fresh bootstrap targets do not; their canonical row and provenance are imported from SQLite later.
INSERT OR IGNORE INTO life360_holding_anchors(
    effective_from, effective_to, shares, quality, basis,
    source_document_id, source_locator, notes
)
SELECT
    '2025-12-31',
    NULL,
    37028,
    'DERIVED_HIGH_CONFIDENCE',
    'DERIVED_FROM_2025_FAIR_VALUE',
    sd.id,
    'Annual Report 2025, Note 4 / investments in other shares; share count derived from disclosed fair value and contemporaneous Life360 market value',
    '37,028 common shares is a high-confidence derived holding, not an explicitly reported shareholder-register count. Replace or close this anchor when a newer source-backed holding becomes available.'
FROM source_documents sd
JOIN sources s ON s.id=sd.source_id
WHERE s.code='OTELLO_IR'
  AND sd.external_id='otello-annual-2025'
ORDER BY sd.id DESC
LIMIT 1;

INSERT INTO provenance_records(
    entity_table, entity_id, field_name, source_document_id,
    source_locator, extraction_method, confidence, extracted_value
)
SELECT
    'life360_holding_anchors',
    h.id,
    'shares',
    h.source_document_id,
    h.source_locator,
    'CALCULATED',
    'HIGH',
    CAST(h.shares AS TEXT)
FROM life360_holding_anchors h
WHERE h.effective_from='2025-12-31'
  AND NOT EXISTS (
      SELECT 1
      FROM provenance_records p
      WHERE p.entity_table='life360_holding_anchors'
        AND p.entity_id=h.id
        AND p.field_name='shares'
        AND p.source_document_id=h.source_document_id
        AND COALESCE(p.source_locator, '')=COALESCE(h.source_locator, '')
        AND COALESCE(p.extracted_value, '')=CAST(h.shares AS TEXT)
  );
