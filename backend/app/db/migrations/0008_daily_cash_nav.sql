ALTER TABLE cash_movements
    ADD COLUMN corporate_action_id INTEGER REFERENCES corporate_actions(id);

CREATE UNIQUE INDEX idx_cash_movements_corporate_action
    ON cash_movements(corporate_action_id)
    WHERE corporate_action_id IS NOT NULL;

CREATE TABLE cash_period_calibrations (
    id INTEGER PRIMARY KEY,
    start_anchor_date TEXT NOT NULL,
    end_anchor_date TEXT NOT NULL,
    start_cash_nok TEXT NOT NULL,
    end_cash_nok TEXT NOT NULL,
    known_movements_nok TEXT NOT NULL,
    residual_nok TEXT NOT NULL,
    residual_per_day_nok TEXT NOT NULL,
    calendar_days INTEGER NOT NULL CHECK (calendar_days > 0),
    inputs_hash TEXT NOT NULL,
    quality TEXT NOT NULL DEFAULT 'ANCHORED' CHECK (quality IN ('ANCHORED', 'HIGH_RESIDUAL')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (start_anchor_date, end_anchor_date)
);

CREATE INDEX idx_cash_period_calibrations_dates
    ON cash_period_calibrations(start_anchor_date, end_anchor_date);

CREATE TABLE cash_daily_estimates (
    id INTEGER PRIMARY KEY,
    estimate_date TEXT NOT NULL UNIQUE,
    cash_nok TEXT NOT NULL,
    period_start_date TEXT,
    period_end_date TEXT,
    cumulative_known_movements_nok TEXT NOT NULL DEFAULT '0',
    cumulative_residual_nok TEXT NOT NULL DEFAULT '0',
    quality TEXT NOT NULL CHECK (quality IN ('REPORTED', 'ANCHORED_ESTIMATE', 'FORECAST_PARTIAL')),
    inputs_hash TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_cash_daily_estimates_date ON cash_daily_estimates(estimate_date);
CREATE INDEX idx_cash_daily_estimates_quality ON cash_daily_estimates(quality);
