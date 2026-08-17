-- Cloudflare-only performance indexes. These do not change financial semantics.
CREATE INDEX IF NOT EXISTS idx_buybacks_program_trade
    ON buybacks(program_id, trade_date, id);

CREATE INDEX IF NOT EXISTS idx_nav_snapshots_calc_scope_time
    ON nav_snapshots(calculation_version, nav_scope, as_of_at);
