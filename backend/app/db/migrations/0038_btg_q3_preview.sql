-- Public BTG sector preview, published 08.10.2026. Only explicitly stated
-- prose values are seeded; no amounts are inferred from growth rates/images.
INSERT OR IGNORE INTO sources(code, name, source_type, base_url, is_official, terms_notes)
VALUES ('BTG_PACTUAL', 'BTG Pactual Research', 'OTHER',
        'https://content.btgpactual.com/research', 0, 'Offentlig meglerresearch; ikke selskapsrapporterte resultater.');

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.status', 'PUBLIC_ESTIMATES_AVAILABLE',
        '$.estimates', json((
            SELECT json_group_array(json(value)) FROM (
                SELECT value FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
                WHERE COALESCE(json_extract(value, '$.broker'), '') <> 'BTG Pactual'
                UNION ALL
                SELECT value FROM json_each('[{"metric":"revenue_yoy_pct","label":"Omsetningsvekst år/år","value_pct":28.0,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/home/relatorio/6ac79ea65a2606707e77d83d/Telecom-Tech-Previa-3T26-II"},{"metric":"ebitda_yoy_pct","label":"EBITDA-vekst år/år","value_pct":36.0,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/home/relatorio/6ac79ea65a2606707e77d83d/Telecom-Tech-Previa-3T26-II"},{"metric":"ebitda_margin_pct","label":"EBITDA-margin","value_pct":35.7,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/home/relatorio/6ac79ea65a2606707e77d83d/Telecom-Tech-Previa-3T26-II"},{"metric":"cash_profit_mbrl","label":"Cash profit (BTGs definisjon)","value_mbrl":48.0,"broker":"BTG Pactual","published_date":"2026-10-08","source_url":"https://content.btgpactual.com/research/home/relatorio/6ac79ea65a2606707e77d83d/Telecom-Tech-Previa-3T26-II"}]')
            )
        )),
        '$.note', 'Offentlige meglerhusestimater vises hver for seg; ikke markedskonsensus. Vekst er mot samme kvartal året før. Cash profit følger BTGs definisjon og er ikke ommerket til justert nettoresultat.'
    ),
    as_of_date = MAX(COALESCE(as_of_date, ''), '2026-10-08'),
    published_date = MAX(COALESCE(published_date, ''), '2026-10-08'),
    source_name = 'BTG Pactual',
    source_url = 'https://content.btgpactual.com/research/home/relatorio/6ac79ea65a2606707e77d83d/Telecom-Tech-Previa-3T26-II',
    quality = 'PUBLIC_BROKER_PREVIEW',
    source_document_id = NULL,
    notes = 'BTG Telecom & Tech – Prévia 3T26 (II), Bemobi-avsnittet. Kildeverifiserte vekstrater, margin og cash profit; absolutte omsetnings-/EBITDA-estimater er ikke utledet.',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE fact_type = 'NEXT_QUARTER' AND fact_key = '3Q26'
  AND NOT EXISTS (
      SELECT 1 FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
      WHERE json_extract(value, '$.broker') = 'BTG Pactual'
        AND json_extract(value, '$.published_date') > '2026-10-08'
  );
