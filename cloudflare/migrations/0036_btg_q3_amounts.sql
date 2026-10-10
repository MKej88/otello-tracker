-- Verified Bemobi 3Q26 column, Table 3, page 3 of BTG report 08.10.2026.
-- Replace the same publication with its full table; preserve other brokers and newer notes.
UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.status', 'PUBLIC_ESTIMATES_AVAILABLE',
        '$.estimates', json((
            SELECT json_group_array(json(value)) FROM (
                SELECT value FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
                WHERE COALESCE(json_extract(value, '$.broker'), '') <> 'BTG Pactual'
                UNION ALL
                SELECT value FROM json_each('[{"metric":"revenue_mbrl","label":"Omsetning (netto)","value_mbrl":239.8,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"adjusted_ebitda_mbrl","label":"Justert EBITDA","value_mbrl":85.5,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"adjusted_net_income_mbrl","label":"Justert nettoresultat","value_mbrl":48.0,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"ebitda_margin_pct","label":"Justert EBITDA-margin","value_pct":35.7,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"payments_revenue_mbrl","label":"Omsetning – Payments","value_mbrl":121.3,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"saas_revenue_mbrl","label":"Omsetning – SaaS","value_mbrl":47.8,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"subscriptions_revenue_mbrl","label":"Omsetning – Subscriptions","value_mbrl":49.9,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"microfinance_revenue_mbrl","label":"Omsetning – Microfinance","value_mbrl":20.8,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"capex_mbrl","label":"Capex","value_mbrl":15.6,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"capex_to_sales_pct","label":"Capex / omsetning","value_pct":6.5,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"operating_free_cash_flow_mbrl","label":"Operasjonell fri kontantstrøm (OpFCF)","value_mbrl":69.9,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf","source_page":3,"source_evidence":"PDF_TABLE_VERIFIED"}]')
            )
        )),
        '$.note', 'BTG Pactuals 3Q26-estimater fra tabell 3 på side 3 i rapporten 08.10.2026. Beløp i millioner BRL. Justert nettoresultat følger tabellens Adj. Net Income. Capex er investeringer; lavere capex er ikke automatisk et svakere resultat. Meglerhusestimater, ikke markedskonsensus.'
    ),
    as_of_date = MAX(COALESCE(as_of_date, ''), '2026-10-08'),
    published_date = MAX(COALESCE(published_date, ''), '2026-10-08'),
    source_name = 'BTG Pactual',
    source_url = 'https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf',
    quality = 'PUBLIC_BROKER_PREVIEW_PDF_VERIFIED',
    source_document_id = NULL,
    notes = 'BTG Telecom & Tech – Prévia 3T26 (II), tabell 3 side 3, kolonne 3Q26. Alle 11 måltall er visuelt verifisert mot vedlagt PDF; ingen beløp er beregnet fra vekstrater.',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE fact_type = 'NEXT_QUARTER' AND fact_key = '3Q26'
  AND NOT EXISTS (
      SELECT 1 FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
      WHERE json_extract(value, '$.broker') = 'BTG Pactual'
        AND json_extract(value, '$.published_date') > '2026-10-08'
  );
