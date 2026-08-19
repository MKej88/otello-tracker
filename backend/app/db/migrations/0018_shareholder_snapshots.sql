CREATE TABLE shareholder_snapshots (
    id INTEGER PRIMARY KEY,
    snapshot_date TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'EURONEXT_OMS' CHECK (source_kind IN ('EURONEXT_OMS', 'OTELLO_IR_XLSX', 'MANUAL_VERIFIED')),
    total_issued_shares INTEGER,
    treasury_shares INTEGER,
    outstanding_shares INTEGER,
    captured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    notes TEXT,
    UNIQUE (snapshot_date, source_kind)
);

CREATE INDEX idx_shareholder_snapshots_date ON shareholder_snapshots(snapshot_date DESC);

CREATE TABLE shareholder_snapshot_rows (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES shareholder_snapshots(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK (rank > 0),
    shareholder_name TEXT NOT NULL,
    country TEXT,
    shares INTEGER NOT NULL CHECK (shares >= 0),
    ownership_pct TEXT,
    account_type TEXT,
    notes TEXT,
    UNIQUE (snapshot_id, rank),
    UNIQUE (snapshot_id, shareholder_name)
);

CREATE INDEX idx_shareholder_rows_snapshot_rank ON shareholder_snapshot_rows(snapshot_id, rank);
CREATE INDEX idx_shareholder_rows_name ON shareholder_snapshot_rows(shareholder_name);
