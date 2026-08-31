DELETE FROM bemobi_forward_consensus_snapshots
WHERE lower(source_name) = 'marketscreener';

DELETE FROM bemobi_investor_facts
WHERE fact_type = 'FORWARD_CONSENSUS'
  AND lower(source_name) = 'marketscreener';

INSERT INTO bemobi_investor_facts(
    fact_type, fact_key, as_of_date, published_date, payload_json,
    source_name, source_url, quality, notes
) VALUES
    (
        'FORWARD_CONSENSUS', '2026', '2026-05-12', '2026-05-12',
        '{"year":2026,"revenue_mbrl":814.0,"ebitda_mbrl":267.0,"net_income_mbrl":173.0,"eps_brl":2.10,"net_debt_mbrl":-343.0}',
        'BTG Pactual',
        'https://content.btgpactual.com/research/files/file/pt-BR/2026-05-13T153020.415_Bemobi__BMOB3____Resultado_do_1T26.pdf',
        'PUBLIC_BROKER_MODEL',
        'Kildeverifisert offentlig BTG Pactual-modell fra 1Q26-review. Netto kontantbeholdning er lagret som negativ nettogjeld.'
    ),
    (
        'FORWARD_CONSENSUS', '2027', '2026-05-12', '2026-05-12',
        '{"year":2027,"revenue_mbrl":916.0,"ebitda_mbrl":308.0,"net_income_mbrl":189.0,"eps_brl":2.20,"net_debt_mbrl":-322.0}',
        'BTG Pactual',
        'https://content.btgpactual.com/research/files/file/pt-BR/2026-05-13T153020.415_Bemobi__BMOB3____Resultado_do_1T26.pdf',
        'PUBLIC_BROKER_MODEL',
        'Kildeverifisert offentlig BTG Pactual-modell fra 1Q26-review. Netto kontantbeholdning er lagret som negativ nettogjeld.'
    );

INSERT INTO bemobi_forward_consensus_snapshots(
    source_name, observed_date, payload_json, content_hash,
    source_url, source_document_id, quality
) VALUES (
    'BTG Pactual',
    '2026-05-12',
    '{"years":[{"ebitda_mbrl":267.0,"eps_brl":2.1,"net_debt_mbrl":-343.0,"net_income_mbrl":173.0,"revenue_mbrl":814.0,"year":2026},{"ebitda_mbrl":308.0,"eps_brl":2.2,"net_debt_mbrl":-322.0,"net_income_mbrl":189.0,"revenue_mbrl":916.0,"year":2027}]}',
    '1e1e459d3d05beef28ccb80d6563124b26401df4c4dd8357ee4dc00035452b94',
    'https://content.btgpactual.com/research/files/file/pt-BR/2026-05-13T153020.415_Bemobi__BMOB3____Resultado_do_1T26.pdf',
    NULL,
    'PUBLIC_BROKER_MODEL_BASELINE'
);

UPDATE sources
SET is_active = 0,
    terms_notes = 'Retired: automated aggregator ingestion removed in favor of public broker research.'
WHERE code = 'MARKETSCREENER';
