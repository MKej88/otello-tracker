-- Seed the latest four statutory parent net-income quarters so the payout run-rate is
-- available immediately after deploy. Future quarters are refreshed from CVM ITR/DFP.

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.reported_net_income_parent_mbrl', 41.019,
        '$.reported_net_income_parent_source', 'CVM ITR',
        '$.reported_net_income_parent_source_url', 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2025.zip',
        '$.reported_net_income_parent_quality', 'CVM_OFFICIAL_DRE_CON',
        '$.reported_net_income_parent_account', '3.11.01',
        '$.reported_net_income_parent_as_of_date', '2025-09-30'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'TTM_QUARTER' AND fact_key = '3Q25';

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.reported_net_income_parent_mbrl', 51.236,
        '$.reported_net_income_parent_source', 'CVM DFP / ITR',
        '$.reported_net_income_parent_source_url', 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2025.zip',
        '$.reported_net_income_parent_quality', 'CVM_OFFICIAL_DRE_CON',
        '$.reported_net_income_parent_account', '3.11.01',
        '$.reported_net_income_parent_as_of_date', '2025-12-31'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'TTM_QUARTER' AND fact_key = '4Q25';

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.reported_net_income_parent_mbrl', 34.210,
        '$.reported_net_income_parent_source', 'CVM ITR',
        '$.reported_net_income_parent_source_url', 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2026.zip',
        '$.reported_net_income_parent_quality', 'CVM_OFFICIAL_DRE_CON',
        '$.reported_net_income_parent_account', '3.11.01',
        '$.reported_net_income_parent_as_of_date', '2026-03-31'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'TTM_QUARTER' AND fact_key = '1Q26';

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.reported_net_income_parent_mbrl', 33.235,
        '$.reported_net_income_parent_source', 'CVM ITR',
        '$.reported_net_income_parent_source_url', 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2026.zip',
        '$.reported_net_income_parent_quality', 'CVM_OFFICIAL_DRE_CON',
        '$.reported_net_income_parent_account', '3.11.01',
        '$.reported_net_income_parent_as_of_date', '2026-06-30'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'TTM_QUARTER' AND fact_key = '2Q26';
