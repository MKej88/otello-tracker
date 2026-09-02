CREATE TABLE estimated_nav_history_points (
    date TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    nav_total_mnok REAL NOT NULL,
    nav_per_share_nok REAL NOT NULL,
    otec_price_nok REAL,
    discount_pct REAL,
    shares_outstanding INTEGER NOT NULL,
    accounting_nav_per_share_nok REAL,
    composition_json TEXT NOT NULL,
    reconciliation_residual_mnok REAL,
    quality TEXT NOT NULL CHECK (quality = 'VALID'),
    calculated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (date, calculation_version)
);

CREATE INDEX idx_estimated_nav_history_period
    ON estimated_nav_history_points(calculation_version, quality, date);
