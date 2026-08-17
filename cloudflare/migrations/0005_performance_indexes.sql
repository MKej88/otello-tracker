-- Phase 15.4.7 Worker/D1 performance indexes. Financial semantics are unchanged.
CREATE INDEX IF NOT EXISTS idx_market_prices_instrument_type_date
    ON market_prices(instrument_id, price_type, trading_date, observed_at);

CREATE INDEX IF NOT EXISTS idx_fx_rates_pair_calendar_date
    ON fx_rates(base_currency, quote_currency, substr(observed_at, 1, 10), observed_at);

CREATE INDEX IF NOT EXISTS idx_nav_snapshots_calc_scope_calendar_date
    ON nav_snapshots(calculation_version, nav_scope, substr(as_of_at, 1, 10), as_of_at);

CREATE INDEX IF NOT EXISTS idx_job_runs_name_status_finished
    ON job_runs(job_name, status, finished_at, id);

CREATE INDEX IF NOT EXISTS idx_source_documents_source_published
    ON source_documents(source_id, published_at, external_id);

CREATE INDEX IF NOT EXISTS idx_corporate_actions_issuer_type_window
    ON corporate_actions(issuer_instrument_id, action_type, ex_date, payment_date);
