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

CREATE INDEX idx_company_news_issuer_time ON company_news(issuer_instrument_id, published_at);
CREATE INDEX idx_company_news_category_status ON company_news(category, processing_status);
