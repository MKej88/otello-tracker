UPDATE bemobi_investor_facts
SET as_of_date = '2026-09-14',
    published_date = '2026-09-14',
    payload_json = '{"year":2026,"revenue_mbrl":936.0,"ebitda_mbrl":322.0,"net_income_mbrl":166.0,"adjusted_net_income_mbrl":199.0,"ebitda_margin_pct":34.4,"pe_reported":13.5,"ev_ebitda_reported":6.6}',
    source_name = 'XP',
    source_url = 'https://conteudos.xpi.com.br/wp-content/uploads/2026/09/BMOB_2Q26_Update_b0ccd4.pdf',
    quality = 'PUBLIC_BROKER_MODEL',
    notes = 'Kildeverifisert offentlig XP-modelloppdatering etter 2Q26. Nettoresultat er ordinært Net Income i XP-tabellen; Adjusted Net Income lagres separat. XP-tabellen oppgir ikke EPS eller netto gjeld/cash i dette estimatsettet.'
WHERE fact_type = 'FORWARD_CONSENSUS'
  AND fact_key = '2026';

UPDATE bemobi_investor_facts
SET as_of_date = '2026-09-14',
    published_date = '2026-09-14',
    payload_json = '{"year":2027,"revenue_mbrl":1074.0,"ebitda_mbrl":378.0,"net_income_mbrl":194.0,"adjusted_net_income_mbrl":231.0,"ebitda_margin_pct":35.2,"pe_reported":11.6,"ev_ebitda_reported":5.6}',
    source_name = 'XP',
    source_url = 'https://conteudos.xpi.com.br/wp-content/uploads/2026/09/BMOB_2Q26_Update_b0ccd4.pdf',
    quality = 'PUBLIC_BROKER_MODEL',
    notes = 'Kildeverifisert offentlig XP-modelloppdatering etter 2Q26. Nettoresultat er ordinært Net Income i XP-tabellen; Adjusted Net Income lagres separat. XP-tabellen oppgir ikke EPS eller netto gjeld/cash i dette estimatsettet.'
WHERE fact_type = 'FORWARD_CONSENSUS'
  AND fact_key = '2027';

INSERT INTO bemobi_investor_facts(
    fact_type, fact_key, as_of_date, published_date, payload_json,
    source_name, source_url, quality, notes
) VALUES (
    'REFERENCE_MODEL',
    'XP-2026-09-14',
    '2026-09-14',
    '2026-09-14',
    '{"broker":"XP","rating":"BUY","target_price_brl":32.5,"published_date":"2026-09-14","target_period":"YE2027","pe_2027_reported":11.6,"ev_ebitda_2027_reported":5.6,"dividend_yield_pct_approx":9.0,"source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-crescimento-perfil-defensivo-alocacao-de-capital-valuation-compra/","note":"XP løftet kursmålet fra R$31,0 til R$32,5 for utgangen av 2027 og gjentok kjøpsanbefalingen."}',
    'XP',
    'https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-crescimento-perfil-defensivo-alocacao-de-capital-valuation-compra/',
    'PUBLIC_BROKER_MODEL',
    'Offentlig XP-modelloppdatering publisert 14.09.2026 etter 2Q26.'
);

INSERT INTO bemobi_forward_consensus_snapshots(
    source_name, observed_date, payload_json, content_hash,
    source_url, source_document_id, quality
) VALUES (
    'XP',
    '2026-09-14',
    '{"years":[{"ebitda_mbrl":322.0,"net_income_mbrl":166.0,"revenue_mbrl":936.0,"year":2026},{"ebitda_mbrl":378.0,"net_income_mbrl":194.0,"revenue_mbrl":1074.0,"year":2027}]}',
    'b3bd4607b9025b16262a2db0beb27d3df3bf8eca7086450cafa89599423c22fe',
    'https://conteudos.xpi.com.br/wp-content/uploads/2026/09/BMOB_2Q26_Update_b0ccd4.pdf',
    NULL,
    'PUBLIC_BROKER_MODEL_SNAPSHOT'
);

UPDATE bemobi_consensus_events
SET model_revision_json = '{"after_date":"2026-09-14","before_date":"2026-03-30","broker":"XP","estimate_revisions":[],"note":"XP publiserte en ny full modell etter 2Q26 og løftet kursmålet fra R$31,0 til R$32,5 for utgangen av 2027.","source_url":"https://conteudos.xpi.com.br/acoes/relatorios/bemobi-bmob3-crescimento-perfil-defensivo-alocacao-de-capital-valuation-compra/","status":"PUBLIC_UPDATE","target_after_brl":32.5,"target_before_brl":31.0}',
    quality = 'CURATED_PUBLIC_HISTORY',
    notes = 'Oppdatert med offentlig XP-modell publisert 14.09.2026 etter 2Q26.',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE period = '2Q26';
