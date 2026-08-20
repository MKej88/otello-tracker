CREATE TABLE bemobi_forward_consensus_snapshots (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    observed_date TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_url TEXT,
    source_document_id INTEGER REFERENCES source_documents(id),
    quality TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_name, observed_date, content_hash)
);

CREATE INDEX idx_bemobi_forward_consensus_snapshots_source_date
    ON bemobi_forward_consensus_snapshots(source_name, observed_date, id);

CREATE TABLE bemobi_consensus_events (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL UNIQUE,
    result_date TEXT NOT NULL,
    result_source TEXT NOT NULL,
    result_source_url TEXT,
    model_revision_json TEXT NOT NULL,
    quality TEXT NOT NULL,
    notes TEXT,
    source_document_id INTEGER REFERENCES source_documents(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_bemobi_consensus_events_result_date
    ON bemobi_consensus_events(result_date, id);

INSERT INTO bemobi_consensus_events(
    period, result_date, result_source, result_source_url,
    model_revision_json, quality, notes
) VALUES
    ('3Q25','2025-11-13','Otello / Euronext','https://live.euronext.com/en/products/equities/company-news/2025-11-14-bemobi-3q25-reporting','{"after_date":"2025-11-14","before_date":"2025-10-29","broker":"XP","estimate_revisions":[],"note":"XP opprettholdt kjøpsanbefaling og kursmål R$30,5 etter 3Q25.","source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-revisao-do-3t25-resultados-fortes-superando-expectativas-e-acelerando-a-receita/","status":"PUBLIC_UPDATE","target_after_brl":30.5,"target_before_brl":30.5}','CURATED_PUBLIC_HISTORY','Migrert fra tidligere kodebasert konsensushistorikk.'),
    ('4Q25','2026-03-19','Otello / Euronext','https://live.euronext.com/en/products/equities/company-news/2026-03-20-bemobi-4q25-reporting','{"after_date":"2026-03-30","before_date":"2025-11-14","broker":"XP","estimate_revisions":[{"after":26.0,"after_source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-atualizacao-do-modelo-e-comentarios-do-nosso-ndr-com-o-cfo-e-ri-da-bemobi/","before":14.0,"before_source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-outro-trimestre-forte/","change_pp":12.0,"label":"2026E omsetningsvekst","note":"Ikke en ren rapportrevisjon: den senere modellen inkluderer Paytime.","unit":"pct"}],"note":"XP løftet kursmålet fra R$30,5 til R$31,0 i modelloppdateringen etter 4Q25. Oppdateringen inkluderte også konsolideringen av Paytime.","source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-atualizacao-do-modelo-e-comentarios-do-nosso-ndr-com-o-cfo-e-ri-da-bemobi/","status":"PUBLIC_UPDATE","target_after_brl":31.0,"target_before_brl":30.5}','CURATED_PUBLIC_HISTORY','Migrert fra tidligere kodebasert konsensushistorikk.'),
    ('2Q26','2026-08-11','XP resultatreview','https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-forte-resultado-com-pagamentos-e-saas-impulsionando-o-crescimento/','{"after_date":null,"before_date":"2026-03-30","broker":"XP","checked_date":"2026-08-20","estimate_revisions":[],"note":"2Q26-reviewen er publisert, men ingen ny offentlig XP-modell/kursmålrevisjon er verifisert ennå.","source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-forte-resultado-com-pagamentos-e-saas-impulsionando-o-crescimento/","status":"WAITING_FOR_PUBLIC_POST_REPORT_MODEL","target_after_brl":null,"target_before_brl":31.0}','CURATED_PUBLIC_HISTORY','Migrert fra tidligere kodebasert konsensushistorikk.');

INSERT INTO bemobi_forward_consensus_snapshots(
    source_name, observed_date, payload_json, content_hash,
    source_url, source_document_id, quality
) VALUES (
    'MarketScreener',
    '2026-08-19',
    '{"years":[{"ebit_mbrl":205.4,"ebitda_mbrl":288.2,"eps_brl":2.07,"net_debt_mbrl":-226.0,"net_income_mbrl":174.3,"revenue_mbrl":814.0,"year":2026},{"ebit_mbrl":257.1,"ebitda_mbrl":342.5,"eps_brl":2.16,"net_debt_mbrl":-208.0,"net_income_mbrl":191.6,"revenue_mbrl":1002.0,"year":2027}]}',
    'c46bd466f19dbfa93584b2fe35255404baf65dae14d3ea06a4a9fcb0944dd239',
    'https://www.marketscreener.com/quote/stock/BEMOBI-MOBILE-TECH-S-A-119084218/finances/',
    NULL,
    'PUBLIC_AGGREGATE_BASELINE'
);
