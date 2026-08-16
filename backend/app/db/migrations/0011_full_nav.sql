CREATE TABLE other_net_assets_reported_anchors (
    id INTEGER PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    total_assets_reported TEXT NOT NULL,
    cash_reported TEXT NOT NULL,
    bemobi_carrying_reported TEXT NOT NULL,
    total_liabilities_reported TEXT NOT NULL,
    reported_currency TEXT NOT NULL DEFAULT 'USD',
    other_net_assets_reported TEXT NOT NULL,
    precision_status TEXT NOT NULL DEFAULT 'EXACT',
    restated INTEGER NOT NULL DEFAULT 0 CHECK (restated IN (0, 1)),
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    source_locator TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (as_of_date, source_document_id)
);

CREATE INDEX idx_other_net_assets_reported_date
    ON other_net_assets_reported_anchors(as_of_date);

ALTER TABLE other_net_assets_anchors ADD COLUMN reported_anchor_id INTEGER REFERENCES other_net_assets_reported_anchors(id);
ALTER TABLE other_net_assets_anchors ADD COLUMN amount_usd TEXT;
ALTER TABLE other_net_assets_anchors ADD COLUMN fx_rate_to_nok TEXT;
ALTER TABLE other_net_assets_anchors ADD COLUMN quality TEXT;
ALTER TABLE other_net_assets_anchors ADD COLUMN inputs_hash TEXT;

CREATE UNIQUE INDEX idx_other_net_assets_anchor_reported
    ON other_net_assets_anchors(reported_anchor_id)
    WHERE reported_anchor_id IS NOT NULL;

CREATE TABLE other_net_assets_daily_estimates (
    estimate_date TEXT PRIMARY KEY,
    amount_usd TEXT NOT NULL,
    usd_nok_rate TEXT NOT NULL,
    amount_nok TEXT NOT NULL,
    quality TEXT NOT NULL CHECK (quality IN ('REPORTED_ANCHOR', 'INTERPOLATED', 'FORECAST_PARTIAL')),
    start_anchor_id INTEGER NOT NULL REFERENCES other_net_assets_reported_anchors(id),
    end_anchor_id INTEGER REFERENCES other_net_assets_reported_anchors(id),
    inputs_hash TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_other_net_assets_daily_quality
    ON other_net_assets_daily_estimates(quality, estimate_date);
