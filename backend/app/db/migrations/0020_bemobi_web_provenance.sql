ALTER TABLE bemobi_investor_facts
    ADD COLUMN source_document_id INTEGER REFERENCES source_documents(id);

CREATE INDEX idx_bemobi_investor_facts_source_document
    ON bemobi_investor_facts(source_document_id);

INSERT OR IGNORE INTO sources(
    code, name, source_type, base_url, is_official, is_active, terms_notes
) VALUES
    (
        'MARKETSCREENER',
        'MarketScreener',
        'OTHER',
        'https://www.marketscreener.com/',
        0,
        1,
        'Offentlig aggregert markeds-/konsensuskilde. Best-effort; skal aldri overskrive siste gode data ved parser- eller nettfeil.'
    ),
    (
        'XP',
        'XP Investimentos',
        'OTHER',
        'https://conteudos.xpi.com.br/',
        0,
        1,
        'Offentlige meglerartikler og forhåndsestimater. Ingen omgåelse av innlogging eller betalingsmur.'
    );
