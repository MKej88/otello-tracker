CREATE TABLE estimated_nav_history_retry_queue (
    date TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    reason TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts > 0),
    first_failed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_failed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    next_retry_at TEXT NOT NULL,
    PRIMARY KEY (date, calculation_version)
);

CREATE INDEX idx_estimated_nav_history_retry_due
    ON estimated_nav_history_retry_queue(calculation_version, next_retry_at, date);
