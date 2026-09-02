-- GENERATED FILE. Do not edit by hand.
-- Source: backend/app/db/migrations after the latest applied migration.
-- Regenerate with: python cloudflare/tools/generate_d1_schema.py
-- D1 enforces foreign keys; defer checks while the empty schema is created.
PRAGMA defer_foreign_keys = ON;

-- TABLES
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

CREATE TABLE buyback_daily_transactions (
    id INTEGER PRIMARY KEY,
    weekly_buyback_id INTEGER NOT NULL REFERENCES buybacks(id) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    shares INTEGER NOT NULL CHECK(shares > 0),
    avg_price_nok TEXT NOT NULL,
    amount_nok TEXT NOT NULL,
    trade_count INTEGER NOT NULL CHECK(trade_count > 0),
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    quality TEXT NOT NULL DEFAULT 'CONFIRMED'
        CHECK(quality IN ('CONFIRMED', 'RECONCILED', 'REQUIRES_REVIEW')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(weekly_buyback_id, trade_date)
);

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
    notes TEXT, max_price_nok TEXT,
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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), cumulative_program_avg_price_nok TEXT, cumulative_program_amount_nok TEXT, period_start TEXT,
    UNIQUE (trade_date, source_document_id)
);

CREATE TABLE cash_anchors (
    id INTEGER PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    amount_nok TEXT,
    reported_amount TEXT,
    reported_currency TEXT,
    fx_rate_to_nok TEXT,
    anchor_type TEXT NOT NULL DEFAULT 'REPORTED' CHECK (anchor_type IN ('REPORTED', 'MANUAL_ADJUSTMENT')),
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        amount_nok IS NOT NULL
        OR (reported_amount IS NOT NULL AND reported_currency IS NOT NULL)
    ),
    UNIQUE (as_of_date, anchor_type, source_document_id)
);

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

CREATE TABLE "cash_movements" (
    id INTEGER PRIMARY KEY,
    movement_date TEXT NOT NULL,
    movement_type TEXT NOT NULL CHECK (movement_type IN (
        'BEMOBI_DIVIDEND', 'BEMOBI_JCP', 'OTELLO_BUYBACK', 'OTELLO_BUYBACK_DAILY',
        'OTELLO_DISTRIBUTION', 'OPEX', 'TAX', 'FX', 'OTHER'
    )),
    amount_nok TEXT NOT NULL,
    amount_original TEXT,
    currency TEXT NOT NULL DEFAULT 'NOK',
    fx_rate_to_nok TEXT,
    description TEXT NOT NULL,
    source_document_id INTEGER REFERENCES source_documents(id),
    confidence TEXT NOT NULL DEFAULT 'CONFIRMED'
        CHECK (confidence IN ('CONFIRMED', 'ESTIMATED', 'MANUAL')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    corporate_action_id INTEGER REFERENCES corporate_actions(id),
    buyback_id INTEGER REFERENCES buybacks(id)
, external_movement_id TEXT);

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

CREATE TABLE company_news (
    id INTEGER PRIMARY KEY,
    issuer_instrument_id INTEGER REFERENCES instruments(id),
    source_document_id INTEGER NOT NULL UNIQUE REFERENCES source_documents(id),
    headline TEXT NOT NULL,
    published_at TEXT,
    category TEXT NOT NULL CHECK (category IN ('RESULTS', 'DIVIDEND', 'JCP', 'BUYBACK', 'M_AND_A', 'CAPITAL', 'GUIDANCE', 'CORPORATE', 'OTHER')),
    nav_impact TEXT NOT NULL DEFAULT 'NONE' CHECK (nav_impact IN ('NONE', 'POTENTIAL', 'DIRECT')),
    processing_status TEXT NOT NULL DEFAULT 'NEW' CHECK (processing_status IN ('NEW', 'PARSED', 'REVIEW_REQUIRED', 'APPLIED', 'IGNORED')),
    summary TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

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
, quantity INTEGER CHECK (quantity IS NULL OR quantity >= 0), external_action_id TEXT, gross_amount_per_share TEXT, net_amount_per_share TEXT, gross_total_amount TEXT, net_total_amount TEXT, withholding_rate TEXT, tax_treatment TEXT, component_group TEXT);

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

CREATE TABLE market_activity (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    trading_date TEXT NOT NULL,
    volume_shares INTEGER NOT NULL CHECK (volume_shares >= 0),
    last_price_nok TEXT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    source_document_id INTEGER REFERENCES source_documents(id),
    quality TEXT NOT NULL CHECK (quality IN ('HISTORICAL_EXPORT', 'DELAYED_TRADE_SUM')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (instrument_id, trading_date, source_id)
);

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
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), quality TEXT NOT NULL DEFAULT 'DIRECT'
    CHECK (quality IN ('DIRECT', 'RECONSTRUCTED')), metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (instrument_id, observed_at, price_type, source_id)
);

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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), nav_scope TEXT NOT NULL DEFAULT 'FULL'
    CHECK (nav_scope IN ('FULL', 'CORE')), components_json TEXT NOT NULL DEFAULT '{}', quality_notes TEXT,
    UNIQUE (as_of_at, calculation_version)
);

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

CREATE TABLE other_net_assets_anchors (
    id INTEGER PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    amount_nok TEXT NOT NULL,
    description TEXT NOT NULL,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
, reported_anchor_id INTEGER REFERENCES other_net_assets_reported_anchors(id), amount_usd TEXT, fx_rate_to_nok TEXT, quality TEXT, inputs_hash TEXT);

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
, base_amount_usd TEXT, base_amount_nok TEXT, associated_receivable_nok TEXT NOT NULL DEFAULT '0', receivable_quality TEXT NOT NULL DEFAULT 'NONE', receivable_components_json TEXT);

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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), associated_receivable_reported TEXT NOT NULL DEFAULT '0', base_other_net_assets_reported TEXT,
    UNIQUE (as_of_date, source_document_id)
);

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

CREATE TABLE runtime_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
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

CREATE TABLE source_health (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OK', 'DEGRADED', 'DOWN')),
    latency_ms INTEGER,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

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


-- INDEXS
CREATE INDEX idx_bemobi_holdings_effective ON bemobi_holdings(effective_from, effective_to);

CREATE INDEX idx_broker_estimate_sets_period ON broker_estimate_sets(period, published_at);

CREATE INDEX idx_broker_estimate_values_metric ON broker_estimate_values(metric);

CREATE INDEX idx_buyback_daily_transactions_date
    ON buyback_daily_transactions(trade_date);

CREATE INDEX idx_buyback_daily_transactions_weekly
    ON buyback_daily_transactions(weekly_buyback_id, trade_date);

CREATE INDEX idx_buybacks_period_start ON buybacks(period_start);

CREATE INDEX idx_buybacks_trade_date ON buybacks(trade_date);

CREATE INDEX idx_cash_anchors_date ON cash_anchors(as_of_date);

CREATE INDEX idx_cash_daily_estimates_date ON cash_daily_estimates(estimate_date);

CREATE INDEX idx_cash_daily_estimates_quality ON cash_daily_estimates(quality);

CREATE INDEX idx_cash_movements_buyback_id ON cash_movements(buyback_id);

CREATE UNIQUE INDEX idx_cash_movements_corporate_action
    ON cash_movements(corporate_action_id)
    WHERE corporate_action_id IS NOT NULL;

CREATE INDEX idx_cash_movements_date ON cash_movements(movement_date);

CREATE UNIQUE INDEX idx_cash_movements_external_movement_id
    ON cash_movements(external_movement_id)
    WHERE external_movement_id IS NOT NULL;

CREATE INDEX idx_cash_movements_type ON cash_movements(movement_type);

CREATE INDEX idx_cash_period_calibrations_dates
    ON cash_period_calibrations(start_anchor_date, end_anchor_date);

CREATE INDEX idx_company_news_category_status ON company_news(category, processing_status);

CREATE INDEX idx_company_news_issuer_time ON company_news(issuer_instrument_id, published_at);

CREATE INDEX idx_consensus_snapshots_period_metric ON consensus_snapshots(period, metric, as_of_at);

CREATE INDEX idx_corporate_actions_component_group
    ON corporate_actions(component_group)
    WHERE component_group IS NOT NULL;

CREATE UNIQUE INDEX idx_corporate_actions_external_action_id
    ON corporate_actions(external_action_id)
    WHERE external_action_id IS NOT NULL;

CREATE INDEX idx_corporate_actions_issuer_date ON corporate_actions(issuer_instrument_id, announcement_date);

CREATE INDEX idx_corporate_actions_payment_date ON corporate_actions(payment_date);

CREATE INDEX idx_fx_rates_pair_time ON fx_rates(base_currency, quote_currency, observed_at);

CREATE UNIQUE INDEX idx_instruments_isin ON instruments(isin) WHERE isin IS NOT NULL;

CREATE INDEX idx_job_runs_name_time ON job_runs(job_name, started_at);

CREATE INDEX idx_market_activity_instrument_date
    ON market_activity(instrument_id, trading_date);

CREATE INDEX idx_market_prices_instrument_date ON market_prices(instrument_id, trading_date);

CREATE INDEX idx_market_prices_observed_at ON market_prices(observed_at);

CREATE INDEX idx_market_prices_quality ON market_prices(quality);

CREATE INDEX idx_nav_snapshots_scope_time
    ON nav_snapshots(nav_scope, as_of_at);

CREATE INDEX idx_nav_snapshots_time ON nav_snapshots(as_of_at);

CREATE INDEX idx_otello_share_counts_effective ON otello_share_counts(effective_from, effective_to);

CREATE UNIQUE INDEX idx_other_net_assets_anchor_reported
    ON other_net_assets_anchors(reported_anchor_id)
    WHERE reported_anchor_id IS NOT NULL;

CREATE INDEX idx_other_net_assets_daily_quality
    ON other_net_assets_daily_estimates(quality, estimate_date);

CREATE INDEX idx_other_net_assets_date ON other_net_assets_anchors(as_of_date);

CREATE INDEX idx_other_net_assets_reported_date
    ON other_net_assets_reported_anchors(as_of_date);

CREATE INDEX idx_provenance_document ON provenance_records(source_document_id);

CREATE INDEX idx_provenance_entity ON provenance_records(entity_table, entity_id);

CREATE INDEX idx_source_documents_published_at ON source_documents(published_at);

CREATE INDEX idx_source_documents_type ON source_documents(document_type);

CREATE INDEX idx_source_health_source_time ON source_health(source_id, checked_at);


-- TRIGGERS
CREATE TRIGGER normalize_newsweb_program_note
AFTER INSERT ON buyback_programs
WHEN NEW.source_document_id IN (
    SELECT sd.id FROM source_documents sd
    JOIN sources s ON s.id = sd.source_id
    WHERE s.code = 'NEWSWEB'
)
BEGIN
    UPDATE buyback_programs
    SET notes = replace(
        NEW.notes,
        'NEWSWEB mirror of Oslo Bors status',
        'Oslo Bors NewsWeb original status'
    )
    WHERE id = NEW.id;
END;

CREATE TRIGGER normalize_newsweb_regulatory_document
AFTER INSERT ON source_documents
WHEN NEW.source_id = (SELECT id FROM sources WHERE code = 'NEWSWEB')
 AND NEW.document_type = 'REGULATORY_NEWS_MIRROR'
BEGIN
    UPDATE source_documents
    SET document_type = 'REGULATORY_NEWS'
    WHERE id = NEW.id;
END;

CREATE TRIGGER normalize_newsweb_share_note_insert
AFTER INSERT ON otello_share_counts
WHEN NEW.source_document_id IN (
    SELECT sd.id FROM source_documents sd
    JOIN sources s ON s.id = sd.source_id
    WHERE s.code = 'NEWSWEB'
)
BEGIN
    UPDATE otello_share_counts
    SET notes = replace(
        NEW.notes,
        'NEWSWEB mirror of Oslo Bors status',
        'Oslo Bors NewsWeb original status'
    )
    WHERE id = NEW.id;
END;

CREATE TRIGGER normalize_newsweb_share_note_update
AFTER UPDATE OF source_document_id, notes ON otello_share_counts
WHEN NEW.source_document_id IN (
    SELECT sd.id FROM source_documents sd
    JOIN sources s ON s.id = sd.source_id
    WHERE s.code = 'NEWSWEB'
)
 AND NEW.notes LIKE '%NEWSWEB mirror of Oslo Bors status%'
BEGIN
    UPDATE otello_share_counts
    SET notes = replace(
        NEW.notes,
        'NEWSWEB mirror of Oslo Bors status',
        'Oslo Bors NewsWeb original status'
    )
    WHERE id = NEW.id;
END;

CREATE TRIGGER prevent_weekly_buyback_cash_when_daily
BEFORE INSERT ON cash_movements
WHEN NEW.movement_type = 'OTELLO_BUYBACK'
 AND EXISTS (
     SELECT 1
     FROM buybacks b
     JOIN buyback_daily_transactions d ON d.weekly_buyback_id = b.id
     WHERE b.trade_date = NEW.movement_date
 )
BEGIN
    SELECT RAISE(IGNORE);
END;

PRAGMA defer_foreign_keys = OFF;
PRAGMA optimize;
