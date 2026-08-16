CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('IR', 'EXCHANGE', 'REGULATOR', 'API', 'MANUAL', 'OTHER')),
    base_url TEXT,
    is_official INTEGER NOT NULL DEFAULT 0 CHECK (is_official IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    terms_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE source_documents (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    external_id TEXT,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    url TEXT NOT NULL,
    content_sha256 TEXT,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (source_id, external_id)
);

CREATE INDEX idx_source_documents_published_at ON source_documents(published_at);
CREATE INDEX idx_source_documents_type ON source_documents(document_type);

CREATE TABLE instruments (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('EQUITY', 'INDEX', 'FUND', 'OTHER')),
    exchange_mic TEXT,
    currency TEXT NOT NULL,
    isin TEXT,
    source_symbol TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (symbol, exchange_mic)
);

CREATE UNIQUE INDEX idx_instruments_isin ON instruments(isin) WHERE isin IS NOT NULL;

CREATE TABLE market_prices (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    observed_at TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    price_type TEXT NOT NULL CHECK (price_type IN ('LAST', 'CLOSE', 'OPEN', 'HIGH', 'LOW', 'VWAP')),
    price TEXT NOT NULL,
    currency TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    source_document_id INTEGER REFERENCES source_documents(id),
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (instrument_id, observed_at, price_type, source_id)
);

CREATE INDEX idx_market_prices_instrument_date ON market_prices(instrument_id, trading_date);
CREATE INDEX idx_market_prices_observed_at ON market_prices(observed_at);

CREATE TABLE fx_rates (
    id INTEGER PRIMARY KEY,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    rate TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    source_document_id INTEGER REFERENCES source_documents(id),
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (base_currency <> quote_currency),
    UNIQUE (base_currency, quote_currency, observed_at, source_id)
);

CREATE INDEX idx_fx_rates_pair_time ON fx_rates(base_currency, quote_currency, observed_at);

CREATE TABLE bemobi_holdings (
    id INTEGER PRIMARY KEY,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    shares INTEGER NOT NULL CHECK (shares >= 0),
    ownership_pct TEXT,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX idx_bemobi_holdings_effective ON bemobi_holdings(effective_from, effective_to);

CREATE TABLE otello_share_counts (
    id INTEGER PRIMARY KEY,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    total_shares INTEGER NOT NULL CHECK (total_shares > 0),
    treasury_shares INTEGER NOT NULL DEFAULT 0 CHECK (treasury_shares >= 0),
    outstanding_shares INTEGER NOT NULL CHECK (outstanding_shares > 0),
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (outstanding_shares = total_shares - treasury_shares),
    CHECK (treasury_shares <= total_shares),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX idx_otello_share_counts_effective ON otello_share_counts(effective_from, effective_to);

CREATE TABLE cash_anchors (
    id INTEGER PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    amount_nok TEXT NOT NULL,
    anchor_type TEXT NOT NULL DEFAULT 'REPORTED' CHECK (anchor_type IN ('REPORTED', 'MANUAL_ADJUSTMENT')),
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (as_of_date, anchor_type, source_document_id)
);

CREATE INDEX idx_cash_anchors_date ON cash_anchors(as_of_date);

CREATE TABLE cash_movements (
    id INTEGER PRIMARY KEY,
    movement_date TEXT NOT NULL,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('BEMOBI_DIVIDEND', 'BEMOBI_JCP', 'OTELLO_BUYBACK', 'OTELLO_DISTRIBUTION', 'OPEX', 'TAX', 'FX', 'OTHER')),
    amount_nok TEXT NOT NULL,
    amount_original TEXT,
    currency TEXT NOT NULL DEFAULT 'NOK',
    fx_rate_to_nok TEXT,
    description TEXT NOT NULL,
    source_document_id INTEGER REFERENCES source_documents(id),
    confidence TEXT NOT NULL DEFAULT 'CONFIRMED' CHECK (confidence IN ('CONFIRMED', 'ESTIMATED', 'MANUAL')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_cash_movements_date ON cash_movements(movement_date);
CREATE INDEX idx_cash_movements_type ON cash_movements(movement_type);

CREATE TABLE other_net_assets_anchors (
    id INTEGER PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    amount_nok TEXT NOT NULL,
    description TEXT NOT NULL,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_other_net_assets_date ON other_net_assets_anchors(as_of_date);

CREATE TABLE buyback_programs (
    id INTEGER PRIMARY KEY,
    external_program_id TEXT,
    announced_at TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    max_shares INTEGER,
    max_amount_nok TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'COMPLETED', 'CANCELLED', 'SUPERSEDED')),
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    UNIQUE (external_program_id)
);

CREATE TABLE buybacks (
    id INTEGER PRIMARY KEY,
    program_id INTEGER REFERENCES buyback_programs(id),
    trade_date TEXT NOT NULL,
    shares INTEGER NOT NULL CHECK (shares > 0),
    avg_price_nok TEXT NOT NULL,
    amount_nok TEXT NOT NULL,
    cumulative_program_shares INTEGER,
    treasury_shares_after INTEGER,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (trade_date, source_document_id)
);

CREATE INDEX idx_buybacks_trade_date ON buybacks(trade_date);

CREATE TABLE corporate_actions (
    id INTEGER PRIMARY KEY,
    issuer_instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    action_type TEXT NOT NULL CHECK (action_type IN ('DIVIDEND', 'JCP', 'BUYBACK', 'SHARE_CANCELLATION', 'SPLIT', 'REVERSE_SPLIT', 'CAPITAL_INCREASE', 'DISTRIBUTION', 'OTHER')),
    announcement_date TEXT,
    ex_date TEXT,
    record_date TEXT,
    payment_date TEXT,
    amount_per_share TEXT,
    total_amount TEXT,
    currency TEXT,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_corporate_actions_issuer_date ON corporate_actions(issuer_instrument_id, announcement_date);
CREATE INDEX idx_corporate_actions_payment_date ON corporate_actions(payment_date);

CREATE TABLE nav_snapshots (
    id INTEGER PRIMARY KEY,
    as_of_at TEXT NOT NULL,
    nav_total_nok TEXT NOT NULL,
    nav_per_share_nok TEXT NOT NULL,
    otec_price_nok TEXT,
    discount_pct TEXT,
    bemobi_value_nok TEXT NOT NULL,
    cash_estimate_nok TEXT NOT NULL,
    other_net_assets_nok TEXT NOT NULL DEFAULT '0',
    shares_outstanding INTEGER NOT NULL CHECK (shares_outstanding > 0),
    calculation_version TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OK' CHECK (status IN ('OK', 'DEGRADED', 'ESTIMATED', 'BACKFILLED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (as_of_at, calculation_version)
);

CREATE INDEX idx_nav_snapshots_time ON nav_snapshots(as_of_at);

CREATE TABLE broker_estimate_sets (
    id INTEGER PRIMARY KEY,
    broker TEXT NOT NULL,
    period TEXT NOT NULL,
    published_at TEXT NOT NULL,
    recommendation TEXT,
    target_price TEXT,
    target_price_currency TEXT DEFAULT 'BRL',
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    supersedes_id INTEGER REFERENCES broker_estimate_sets(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (broker, period, published_at, source_document_id)
);

CREATE INDEX idx_broker_estimate_sets_period ON broker_estimate_sets(period, published_at);

CREATE TABLE broker_estimate_values (
    id INTEGER PRIMARY KEY,
    estimate_set_id INTEGER NOT NULL REFERENCES broker_estimate_sets(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT NOT NULL,
    currency TEXT,
    scope TEXT NOT NULL DEFAULT 'ADJUSTED',
    UNIQUE (estimate_set_id, metric, scope)
);

CREATE INDEX idx_broker_estimate_values_metric ON broker_estimate_values(metric);

CREATE TABLE consensus_snapshots (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    metric TEXT NOT NULL,
    as_of_at TEXT NOT NULL,
    mean_value TEXT NOT NULL,
    median_value TEXT NOT NULL,
    low_value TEXT NOT NULL,
    high_value TEXT NOT NULL,
    contributor_count INTEGER NOT NULL CHECK (contributor_count > 0),
    weighted_value TEXT,
    methodology_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (period, metric, as_of_at, methodology_version)
);

CREATE INDEX idx_consensus_snapshots_period_metric ON consensus_snapshots(period, metric, as_of_at);

CREATE TABLE provenance_records (
    id INTEGER PRIMARY KEY,
    entity_table TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    source_locator TEXT,
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('API', 'PARSER', 'MANUAL', 'CALCULATED')),
    confidence TEXT NOT NULL DEFAULT 'HIGH' CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
    extracted_value TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_provenance_entity ON provenance_records(entity_table, entity_id);
CREATE INDEX idx_provenance_document ON provenance_records(source_document_id);

CREATE TABLE job_runs (
    id INTEGER PRIMARY KEY,
    job_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED')),
    records_written INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_job_runs_name_time ON job_runs(job_name, started_at);

CREATE TABLE source_health (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OK', 'DEGRADED', 'DOWN')),
    latency_ms INTEGER,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_source_health_source_time ON source_health(source_id, checked_at);
