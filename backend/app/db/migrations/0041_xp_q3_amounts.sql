-- XP Brazil Tech, 16.10.2026, page 2, BMOB3 3Q26e column.
-- Preserve other brokers, confirmed report date and newer XP publications.
UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.status', 'PUBLIC_ESTIMATES_AVAILABLE',
        '$.estimates', json((
            SELECT json_group_array(json(value)) FROM (
                SELECT value FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
                WHERE COALESCE(json_extract(value, '$.broker'), '') <> 'XP'
                UNION ALL
                SELECT value FROM json_each('[{"metric":"revenue_mbrl","label":"Omsetning (netto)","value_mbrl":239,"broker":"XP","published_date":"2026-10-16","source_url":"https://conteudos.xpi.com.br/wp-content/uploads/2026/10/Tech_3Q26-Preview-1.pdf","source_page":2,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"adjusted_ebitda_mbrl","label":"Justert EBITDA","value_mbrl":82,"broker":"XP","published_date":"2026-10-16","source_url":"https://conteudos.xpi.com.br/wp-content/uploads/2026/10/Tech_3Q26-Preview-1.pdf","source_page":2,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"ebitda_margin_pct","label":"Justert EBITDA-margin","value_pct":34.5,"broker":"XP","published_date":"2026-10-16","source_url":"https://conteudos.xpi.com.br/wp-content/uploads/2026/10/Tech_3Q26-Preview-1.pdf","source_page":2,"source_evidence":"PDF_TABLE_VERIFIED"},{"metric":"net_income_mbrl","label":"Ordinært nettoresultat","value_mbrl":41,"broker":"XP","published_date":"2026-10-16","source_url":"https://conteudos.xpi.com.br/wp-content/uploads/2026/10/Tech_3Q26-Preview-1.pdf","source_page":2,"source_evidence":"PDF_TABLE_VERIFIED"}]')
            )
        )),
        '$.note', 'Offentlige meglerhusestimater vises separat. XP: side 2, 16.10.2026. Ordinært nettoresultat er ikke sammenlignbart med BTGs justerte nettoresultat. Beløp i millioner BRL; ikke markedskonsensus.'
    ),
    as_of_date = MAX(COALESCE(as_of_date, ''), '2026-10-16'),
    published_date = MAX(COALESCE(published_date, ''), '2026-10-16'),
    source_name = 'XP',
    source_url = 'https://conteudos.xpi.com.br/wp-content/uploads/2026/10/Tech_3Q26-Preview-1.pdf',
    quality = 'PUBLIC_BROKER_PREVIEW_PDF_VERIFIED',
    source_document_id = NULL,
    notes = 'XP Brazil Tech 3Q26 Preview, 16.10.2026, side 2, BMOB3-tabellens 3Q26e-kolonne. Fire verdier visuelt verifisert mot PDF. Net Income lagres som ordinært nettoresultat.',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE fact_type = 'NEXT_QUARTER' AND fact_key = '3Q26'
  AND NOT EXISTS (
      SELECT 1 FROM json_each(bemobi_investor_facts.payload_json, '$.estimates')
      WHERE json_extract(value, '$.broker') = 'XP'
        AND json_extract(value, '$.published_date') > '2026-10-16'
  );
