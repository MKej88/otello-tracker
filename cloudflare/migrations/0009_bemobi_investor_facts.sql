CREATE TABLE bemobi_investor_facts (
    id INTEGER PRIMARY KEY,
    fact_type TEXT NOT NULL CHECK (fact_type IN (
        'RESULT',
        'OWNERSHIP',
        'TTM_QUARTER',
        'VALUATION_ANCHOR',
        'ANALYST',
        'FORWARD_CONSENSUS',
        'BEAT_MISS',
        'REFERENCE_MODEL',
        'NEXT_QUARTER'
    )),
    fact_key TEXT NOT NULL,
    as_of_date TEXT,
    published_date TEXT,
    payload_json TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT,
    quality TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (fact_type, fact_key)
);

CREATE INDEX idx_bemobi_investor_facts_type_date
    ON bemobi_investor_facts(fact_type, as_of_date, published_date);

INSERT INTO bemobi_investor_facts(
    id, fact_type, fact_key, as_of_date, published_date, payload_json,
    source_name, source_url, quality, notes
) VALUES
    (
        1, 'RESULT', '2Q26', '2026-06-30', '2026-08-11',
        '{"period":"2Q26","period_end":"2026-06-30","published_date":"2026-08-11","adjusted_net_revenue_mbrl":227.3,"adjusted_net_revenue_yoy_pct":29.8,"adjusted_ebitda_mbrl":79.4,"adjusted_ebitda_yoy_pct":32.7,"adjusted_ebitda_margin_pct":34.9,"adjusted_net_income_mbrl":45.2,"adjusted_net_income_yoy_pct":30.1,"ebitda_less_capex_mbrl":64.8,"cash_conversion_pct":81.5,"cash_mbrl":328.0,"payments_yoy_pct":75.0,"saas_yoy_pct":21.0,"quality":"CURATED_FROM_RESULTS_RELEASE"}',
        'Bemobi IR',
        'https://ri.bemobi.com.br/informacoes-financeiras/resultados-trimestrais/',
        'CURATED_FROM_RESULTS_RELEASE',
        'Kuraterte nøkkeltall fra Bemobis 2Q26-resultatpresentasjon.'
    ),
    (
        2, 'OWNERSHIP', '2026-08-19', '2026-08-19', NULL,
        '{"shares":32719588,"ownership_pct":38.22,"bemobi_total_shares":85608392,"checked_date":"2026-08-19","quality":"OFFICIAL_IR_CURRENT"}',
        'Bemobi IR',
        'https://ri.bemobi.com.br/governanca/composicao-acionaria/',
        'OFFICIAL_IR_CURRENT',
        'Otellos eierandel kontrollert mot Bemobis offisielle aksjonærside.'
    ),
    (
        3, 'TTM_QUARTER', '3Q25', '2025-09-30', '2025-10-29',
        '{"period":"3Q25","adjusted_net_income_mbrl":41.0,"adjusted_ebitda_mbrl":62.7,"adjusted_cash_generation_mbrl":47.5,"source":"XP","source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-revisao-do-3t25-resultados-fortes-superando-expectativas-e-acelerando-a-receita/"}',
        'XP',
        'https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-revisao-do-3t25-resultados-fortes-superando-expectativas-e-acelerando-a-receita/',
        'CURATED_PUBLIC_RESULT',
        'Kvartalstall brukt i TTM-verdsettelsen.'
    ),
    (
        4, 'TTM_QUARTER', '4Q25', '2025-12-31', '2026-02-01',
        '{"period":"4Q25","adjusted_net_income_mbrl":61.0,"adjusted_ebitda_mbrl":66.0,"adjusted_cash_generation_mbrl":52.5,"source":"XP / CVM","source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-execucao-segue-solida-sustentando-crescimento-consistente-e-forte-geracao-de-caixa/"}',
        'XP / CVM',
        'https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-execucao-segue-solida-sustentando-crescimento-consistente-e-forte-geracao-de-caixa/',
        'CURATED_PUBLIC_RESULT',
        'Kvartalstall brukt i TTM-verdsettelsen.'
    ),
    (
        5, 'TTM_QUARTER', '1Q26', '2026-03-31', '2026-05-11',
        '{"period":"1Q26","adjusted_net_income_mbrl":37.0,"adjusted_ebitda_mbrl":75.0,"adjusted_cash_generation_mbrl":61.4,"source":"Bemobi / CVM","source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-surpresa-positiva-solida-com-pagamentos-e-saas-impulsionando-o-crescimento/"}',
        'Bemobi / CVM',
        'https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-surpresa-positiva-solida-com-pagamentos-e-saas-impulsionando-o-crescimento/',
        'CURATED_PUBLIC_RESULT',
        'Kvartalstall brukt i TTM-verdsettelsen.'
    ),
    (
        6, 'TTM_QUARTER', '2Q26', '2026-06-30', '2026-08-11',
        '{"period":"2Q26","adjusted_net_income_mbrl":45.2,"adjusted_ebitda_mbrl":79.4,"adjusted_cash_generation_mbrl":64.8,"source":"Bemobi / CVM","source_url":"https://ri.bemobi.com.br/informacoes-financeiras/resultados-trimestrais/"}',
        'Bemobi / CVM',
        'https://ri.bemobi.com.br/informacoes-financeiras/resultados-trimestrais/',
        'CURATED_FROM_RESULTS_RELEASE',
        'Kvartalstall brukt i TTM-verdsettelsen.'
    ),
    (
        7, 'VALUATION_ANCHOR', '2Q26', '2026-06-30', '2026-08-11',
        '{"period":"2Q26","ttm_ebit_mbrl":175.08,"net_debt_mbrl":-287.2,"cash_position_mbrl":328.0,"quality":"CVM_DERIVED_APPROX","source":"CVM-derived / Bemobi 2Q26","source_url":"https://sabbius.com.br/company/show/BMOB3"}',
        'CVM-derived / Bemobi 2Q26',
        'https://sabbius.com.br/company/show/BMOB3',
        'CVM_DERIVED_APPROX',
        'Standardisert EBIT TTM og omtrentlig netto kontantanker for EV-beregning.'
    ),
    (
        8, 'ANALYST', 'BTG Pactual', '2026-08-19', '2025-11-11',
        '{"institution":"BTG Pactual","analyst":"Osni Carfi","rating":"BUY","target_price_brl":35.0,"last_update":"2025-11-11"}',
        'Bemobi IR',
        'https://ri.bemobi.com.br/nossas-acoes/cobertura-de-analistas-2/',
        'OFFICIAL_IR_CURRENT',
        'Analytikerdekning kontrollert mot Bemobi IR 19.08.2026.'
    ),
    (
        9, 'ANALYST', 'Itaú BBA', '2026-08-19', '2026-04-15',
        '{"institution":"Itaú BBA","analyst":"Maria Clara Infantozzi","rating":"BUY","target_price_brl":33.8,"last_update":"2026-04-15"}',
        'Bemobi IR',
        'https://ri.bemobi.com.br/nossas-acoes/cobertura-de-analistas-2/',
        'OFFICIAL_IR_CURRENT',
        'Analytikerdekning kontrollert mot Bemobi IR 19.08.2026.'
    ),
    (
        10, 'ANALYST', 'Morgan Stanley', '2026-08-19', '2026-06-11',
        '{"institution":"Morgan Stanley","analyst":"Cesar Medina","rating":"HOLD","target_price_brl":24.0,"last_update":"2026-06-11"}',
        'Bemobi IR',
        'https://ri.bemobi.com.br/nossas-acoes/cobertura-de-analistas-2/',
        'OFFICIAL_IR_CURRENT',
        'Analytikerdekning kontrollert mot Bemobi IR 19.08.2026.'
    ),
    (
        11, 'ANALYST', 'XP', '2026-08-19', '2026-03-30',
        '{"institution":"XP","analyst":"Bernardo Guttmann","rating":"BUY","target_price_brl":31.0,"last_update":"2026-03-30"}',
        'Bemobi IR',
        'https://ri.bemobi.com.br/nossas-acoes/cobertura-de-analistas-2/',
        'OFFICIAL_IR_CURRENT',
        'Analytikerdekning kontrollert mot Bemobi IR 19.08.2026.'
    ),
    (
        12, 'FORWARD_CONSENSUS', '2026', '2026-08-19', NULL,
        '{"year":2026,"revenue_mbrl":814.0,"ebitda_mbrl":288.2,"ebit_mbrl":205.4,"net_income_mbrl":174.3,"eps_brl":2.07,"net_debt_mbrl":-226.0}',
        'MarketScreener',
        'https://www.marketscreener.com/quote/stock/BEMOBI-MOBILE-TECH-S-A-119084218/finances/',
        'PUBLIC_AGGREGATE',
        'Offentlig aggregert årsprognose. Kilden viser ikke et komplett hus-for-hus estimatsett, så antall bidragsytere per linje vises ikke.'
    ),
    (
        13, 'FORWARD_CONSENSUS', '2027', '2026-08-19', NULL,
        '{"year":2027,"revenue_mbrl":1002.0,"ebitda_mbrl":342.5,"ebit_mbrl":257.1,"net_income_mbrl":191.6,"eps_brl":2.16,"net_debt_mbrl":-208.0}',
        'MarketScreener',
        'https://www.marketscreener.com/quote/stock/BEMOBI-MOBILE-TECH-S-A-119084218/finances/',
        'PUBLIC_AGGREGATE',
        'Offentlig aggregert årsprognose. Kilden viser ikke et komplett hus-for-hus estimatsett, så antall bidragsytere per linje vises ikke.'
    ),
    (
        14, 'BEAT_MISS', '3Q25', '2025-09-30', '2025-10-29',
        '{"period":"3Q25","broker":"XP","published_date":"2025-10-29","metrics":[{"metric":"adjusted_ebitda_mbrl","label":"Justert EBITDA","estimate":61.0,"actual":62.7},{"metric":"adjusted_net_income_mbrl","label":"Justert resultat","estimate":39.0,"actual":41.0}]}',
        'XP',
        'https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-outro-trimestre-forte/',
        'PUBLIC_BROKER_PREVIEW',
        'Offentlig XP-forhåndsestimat sammenlignet med rapportert utfall.'
    ),
    (
        15, 'BEAT_MISS', '4Q25', '2025-12-31', '2026-02-01',
        '{"period":"4Q25","broker":"XP","published_date":"2026-02-01","metrics":[{"metric":"adjusted_ebitda_mbrl","label":"Justert EBITDA","estimate":65.0,"actual":66.0},{"metric":"adjusted_net_income_mbrl","label":"Justert resultat ex-swap","estimate":52.0,"actual":61.0}]}',
        'XP',
        'https://conteudos.xpi.com.br/acoes/relatorios/brasil-tech-previa-4t25/',
        'PUBLIC_BROKER_PREVIEW',
        'Offentlig XP-forhåndsestimat sammenlignet med rapportert utfall.'
    ),
    (
        16, 'BEAT_MISS', '2Q26', '2026-06-30', '2026-07-16',
        '{"period":"2Q26","broker":"XP","published_date":"2026-07-16","metrics":[{"metric":"adjusted_ebitda_mbrl","label":"Justert EBITDA","estimate":77.0,"actual":79.4},{"metric":"adjusted_net_income_mbrl","label":"Justert resultat","estimate":32.0,"actual":45.2}]}',
        'XP',
        'https://conteudos.xpi.com.br/acoes/relatorios/tmt-previa-do-2t26-lwsa3-e-bmob3/',
        'PUBLIC_BROKER_PREVIEW',
        'Offentlig XP-forhåndsestimat sammenlignet med rapportert utfall.'
    ),
    (
        17, 'REFERENCE_MODEL', 'XP-2026-03-30', '2026-03-30', '2026-03-30',
        '{"broker":"XP","rating":"BUY","target_price_brl":31.0,"published_date":"2026-03-30","pe_2026_reported":11.2,"ev_ebitda_2026_reported":6.6,"source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-atualizacao-do-modelo-e-comentarios-do-nosso-ndr-com-o-cfo-e-ri-da-bemobi/","note":"Historisk XP-modell ved publiseringsdato; ikke løpende rekalkulert."}',
        'XP',
        'https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-atualizacao-do-modelo-e-comentarios-do-nosso-ndr-com-o-cfo-e-ri-da-bemobi/',
        'PUBLIC_BROKER_MODEL',
        'Historisk referansemodell.'
    ),
    (
        18, 'NEXT_QUARTER', '3Q26', '2026-08-19', NULL,
        '{"period":"3Q26","report_date":null,"date_quality":"NOT_CONFIRMED","label":"Dato ikke bekreftet av Bemobi","status":"WAITING_FOR_PUBLIC_ESTIMATES","estimates":[],"tracked_metrics":["Nettoomsetning","Justert EBITDA","EBITDA-margin","Justert resultat","EPS"],"note":"Ingen verifiserte offentlige 3Q26-estimater funnet per 19.08.2026."}',
        'Bemobi IR',
        'https://ri.bemobi.com.br/nossas-acoes/calendario-de-eventos/',
        'NOT_CONFIRMED',
        'Neste rapportdato var ikke bekreftet ved siste kontroll.'
    );
