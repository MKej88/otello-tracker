-- Bound Norges Bank freshness lookups to the latest date and latest fetch independently.
-- D1-only performance indexes; no changes to financial rows or source selection.
CREATE INDEX IF NOT EXISTS idx_fx_coverage_date
    ON fx_rates(source_id, base_currency, quote_currency, substr(observed_at,1,10));

CREATE INDEX IF NOT EXISTS idx_fx_coverage_fetch
    ON fx_rates(source_id, base_currency, quote_currency, fetched_at);
