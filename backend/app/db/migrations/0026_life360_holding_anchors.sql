-- Source-backed, effective-dated Life360 holdings used by investor NAV.
-- The initial 37,028-share row is seeded by curated history after source documents exist.
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
