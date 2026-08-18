-- Workers Paid cost/performance hardening. Financial semantics are unchanged.
-- These indexes target the current dashboard, FX backtest and post-anchor cash paths so
-- D1 scans stay bounded as historical data grows.

CREATE INDEX IF NOT EXISTS idx_source_documents_type_id
    ON source_documents(document_type, id);

CREATE INDEX IF NOT EXISTS idx_cash_movements_date_currency_id
    ON cash_movements(movement_date, currency, id);

CREATE INDEX IF NOT EXISTS idx_cash_anchors_type_date_id
    ON cash_anchors(anchor_type, as_of_date, id);

CREATE INDEX IF NOT EXISTS idx_bemobi_holdings_effective_window
    ON bemobi_holdings(effective_from, effective_to, id);

CREATE INDEX IF NOT EXISTS idx_otello_share_counts_effective_id
    ON otello_share_counts(effective_from, id);
