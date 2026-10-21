-- Official NewsWeb amendments and weekly statements form an effective-dated
-- price-cap audit trail. Never rewrite the cap valid at a historical as-of date.
CREATE TABLE IF NOT EXISTS buyback_program_cap_history (
    id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL REFERENCES buyback_programs(id),
    effective_at TEXT NOT NULL,
    max_price_nok TEXT NOT NULL,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    event_kind TEXT NOT NULL CHECK(event_kind IN ('BASELINE', 'STATUS', 'AMENDMENT')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(program_id, source_document_id)
);
CREATE INDEX IF NOT EXISTS idx_buyback_program_cap_history_effective
    ON buyback_program_cap_history(program_id, effective_at DESC, id DESC);
