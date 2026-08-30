-- Backfill harmonized revenue separately so databases that already applied 0029
-- receive the Bemobi result-release series on upgrade.

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.harmonized_net_revenue_mbrl', 187.5,
        '$.harmonized_net_revenue_source', 'Bemobi result release via CVM',
        '$.harmonized_net_revenue_quality', 'OFFICIAL_RESULT_HARMONIZED_BACKFILL',
        '$.harmonized_net_revenue_as_of_date', '2025-09-30'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'TTM_QUARTER' AND fact_key = '3Q25';

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.harmonized_net_revenue_mbrl', 199.2,
        '$.harmonized_net_revenue_source', 'Bemobi result release via CVM',
        '$.harmonized_net_revenue_quality', 'OFFICIAL_RESULT_HARMONIZED_BACKFILL',
        '$.harmonized_net_revenue_as_of_date', '2025-12-31'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'TTM_QUARTER' AND fact_key = '4Q25';

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.harmonized_net_revenue_mbrl', 222.0,
        '$.harmonized_net_revenue_source', 'Bemobi result release via CVM',
        '$.harmonized_net_revenue_quality', 'OFFICIAL_RESULT_HARMONIZED_BACKFILL',
        '$.harmonized_net_revenue_as_of_date', '2026-03-31'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'TTM_QUARTER' AND fact_key = '1Q26';

UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.harmonized_net_revenue_mbrl', 227.3,
        '$.harmonized_net_revenue_source', 'Bemobi result release via CVM',
        '$.harmonized_net_revenue_quality', 'OFFICIAL_RESULT_HARMONIZED_BACKFILL',
        '$.harmonized_net_revenue_as_of_date', '2026-06-30'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'TTM_QUARTER' AND fact_key = '2Q26';
