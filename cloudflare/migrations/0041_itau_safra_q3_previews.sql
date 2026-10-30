-- Add official public article/summaries for Itaú BBA and Safra to Bemobi 3Q26.
-- Other brokers, publication dates, primary source and report date remain unchanged.
-- D1/SQLite parity: duplicate this migration without modification.

-- Itaú BBA: public 3Q26 preview, verified 30.10.2026. No full PDF is claimed.
-- Add only when this broker is absent; preserve any existing/newer broker observations.
UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.status', 'PUBLIC_ESTIMATES_AVAILABLE',
        '$.estimates', json((
            SELECT json_group_array(json(value)) FROM (
                SELECT value FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
                UNION ALL
                SELECT value FROM json_each('[{"metric":"revenue_mbrl","label":"Omsetning (netto)","value_mbrl":242,"broker":"Itaú BBA","source_url":"https://www.itau.com.br/investimentos/analises/bemobi-e-totvs-previa-balancos-3t/","source_evidence":"OFFICIAL_BROKER_ARTICLE_VERIFIED","verified_date":"2026-10-30","publication_date_status":"NOT_STATED_ON_PUBLIC_PAGE"},{"metric":"ebitda_margin_pct","label":"Justert EBITDA-margin","value_pct":34.4,"broker":"Itaú BBA","source_url":"https://www.itau.com.br/investimentos/analises/bemobi-e-totvs-previa-balancos-3t/","source_evidence":"OFFICIAL_BROKER_ARTICLE_VERIFIED","verified_date":"2026-10-30","publication_date_status":"NOT_STATED_ON_PUBLIC_PAGE"},{"metric":"adjusted_net_income_mbrl","label":"Justert nettoresultat","value_mbrl":52,"broker":"Itaú BBA","source_url":"https://www.itau.com.br/investimentos/analises/bemobi-e-totvs-previa-balancos-3t/","source_evidence":"OFFICIAL_BROKER_ARTICLE_VERIFIED","verified_date":"2026-10-30","publication_date_status":"NOT_STATED_ON_PUBLIC_PAGE"},{"metric":"revenue_yoy_pct","label":"Omsetningsvekst år/år","value_pct":29,"broker":"Itaú BBA","source_url":"https://www.itau.com.br/investimentos/analises/bemobi-e-totvs-previa-balancos-3t/","source_evidence":"OFFICIAL_BROKER_ARTICLE_VERIFIED","verified_date":"2026-10-30","publication_date_status":"NOT_STATED_ON_PUBLIC_PAGE"},{"metric":"organic_revenue_yoy_pct","label":"Organisk omsetningsvekst år/år","value_pct":15,"broker":"Itaú BBA","source_url":"https://www.itau.com.br/investimentos/analises/bemobi-e-totvs-previa-balancos-3t/","source_evidence":"OFFICIAL_BROKER_ARTICLE_VERIFIED","verified_date":"2026-10-30","publication_date_status":"NOT_STATED_ON_PUBLIC_PAGE"},{"metric":"payments_organic_revenue_yoy_pct","label":"Organisk vekst Payments år/år","value_pct":32,"broker":"Itaú BBA","source_url":"https://www.itau.com.br/investimentos/analises/bemobi-e-totvs-previa-balancos-3t/","source_evidence":"OFFICIAL_BROKER_ARTICLE_VERIFIED","verified_date":"2026-10-30","publication_date_status":"NOT_STATED_ON_PUBLIC_PAGE"},{"metric":"saas_revenue_yoy_pct","label":"Omsetningsvekst SaaS år/år","value_pct":22,"broker":"Itaú BBA","source_url":"https://www.itau.com.br/investimentos/analises/bemobi-e-totvs-previa-balancos-3t/","source_evidence":"OFFICIAL_BROKER_ARTICLE_VERIFIED","verified_date":"2026-10-30","publication_date_status":"NOT_STATED_ON_PUBLIC_PAGE"}]')
            )
        )),
        '$.note', COALESCE(json_extract(payload_json, '$.note') || ' ', '') || 'Itaú BBA: tall fra bankens åpne artikkel; publiseringsdato for artikkelen er ikke bekreftet. EBITDA i beløp beregnes kun fra bankens omsetning og oppgitte margin og merkes som beregnet.'
    ),
    as_of_date = MAX(COALESCE(as_of_date, ''), '2026-10-30'),
    quality = 'PUBLIC_BROKER_PREVIEW_MIXED_EVIDENCE',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE fact_type = 'NEXT_QUARTER' AND fact_key = '3Q26'
  AND NOT EXISTS (
      SELECT 1 FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
      WHERE json_extract(value, '$.broker') = 'Itaú BBA'
  );

-- Safra: public 3Q26 preview, verified 30.10.2026. No full PDF is claimed.
-- Add only when this broker is absent; preserve any existing/newer broker observations.
UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.status', 'PUBLIC_ESTIMATES_AVAILABLE',
        '$.estimates', json((
            SELECT json_group_array(json(value)) FROM (
                SELECT value FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
                UNION ALL
                SELECT value FROM json_each('[{"metric":"revenue_mbrl","label":"Omsetning (netto)","value_mbrl":231.9,"broker":"Safra","published_date":"2026-10-23","research_date":"2026-10-22","source_url":"https://oespecialista.safra.com.br/totvs-lwsa-bemobi-intelbras-resultados-3t26/","source_evidence":"BROKER_PUBLISHED_SUMMARY","verified_date":"2026-10-30"},{"metric":"adjusted_ebitda_mbrl","label":"Justert EBITDA","value_mbrl":79.3,"broker":"Safra","published_date":"2026-10-23","research_date":"2026-10-22","source_url":"https://oespecialista.safra.com.br/totvs-lwsa-bemobi-intelbras-resultados-3t26/","source_evidence":"BROKER_PUBLISHED_SUMMARY","verified_date":"2026-10-30"},{"metric":"adjusted_net_income_mbrl","label":"Justert nettoresultat","value_mbrl":43.5,"broker":"Safra","published_date":"2026-10-23","research_date":"2026-10-22","source_url":"https://oespecialista.safra.com.br/totvs-lwsa-bemobi-intelbras-resultados-3t26/","source_evidence":"BROKER_PUBLISHED_SUMMARY","verified_date":"2026-10-30"},{"metric":"payments_revenue_yoy_pct","label":"Omsetningsvekst Payments år/år","value_pct":53,"broker":"Safra","published_date":"2026-10-23","research_date":"2026-10-22","source_url":"https://oespecialista.safra.com.br/totvs-lwsa-bemobi-intelbras-resultados-3t26/","source_evidence":"BROKER_PUBLISHED_SUMMARY","verified_date":"2026-10-30"}]')
            )
        )),
        '$.note', COALESCE(json_extract(payload_json, '$.note') || ' ', '') || 'Safra: tall fra bankens offentlige sammendrag publisert 23.10.2026 (research datert 22.10); ingen original-PDF verifisert. Justert EBITDA-margin beregnes fra publiserte beløp og merkes som beregnet.'
    ),
    as_of_date = MAX(COALESCE(as_of_date, ''), '2026-10-30'),
    quality = 'PUBLIC_BROKER_PREVIEW_MIXED_EVIDENCE',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE fact_type = 'NEXT_QUARTER' AND fact_key = '3Q26'
  AND NOT EXISTS (
      SELECT 1 FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
      WHERE json_extract(value, '$.broker') = 'Safra'
  );
