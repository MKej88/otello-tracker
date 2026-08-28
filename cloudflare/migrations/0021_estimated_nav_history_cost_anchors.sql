-- Source-backed operating-cost anchors for the investor Estimated NAV history.
-- These anchors let the same economic-NAV overlay be evaluated before FY2025.
-- The BASE measure follows the existing policy: recurring employee benefits plus
-- other operating expenses, excluding depreciation, stock compensation and clearly
-- identified non-operational/restructuring items.

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-cost:2023-06-30:base',
    'ECONOMIC_NAV_COST_ANCHOR',
    'Economic NAV operating-cost anchor BASE from 2023-06-30',
    '2023-06-30T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/ZsWAp0aF0TcGJJNc_Report1H24.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-28.1","input_kind":"OPERATING_COST_ANCHOR","scenario":"BASE","effective_from":"2023-06-30","source_period":"1H23","source_period_start":"2023-01-01","source_period_end":"2023-06-30","period_days":181,"amount_usd":"1673000","source_measure":"employee benefits + other operating expenses, excluding depreciation and non-operational items","source_locator":"1H24 comparative 1H23 figures: employee benefits USD 0.973m + other operating expenses USD 0.700m","notes":"Source-backed recurring run-rate for the first half of 2023.","curated":true}'
FROM sources s
WHERE s.code = 'OTELLO_IR';

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-cost:2023-12-31:base',
    'ECONOMIC_NAV_COST_ANCHOR',
    'Economic NAV operating-cost anchor BASE from 2023-12-31',
    '2023-12-31T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/Z7SFmZ7c43Q3f6lX_Report2H24.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-28.1","input_kind":"OPERATING_COST_ANCHOR","scenario":"BASE","effective_from":"2023-12-31","source_period":"2H23","source_period_start":"2023-07-01","source_period_end":"2023-12-31","period_days":184,"amount_usd":"1400000","source_measure":"employee benefits + other operating expenses, excluding depreciation and non-operational items","source_locator":"2H24 comparative 2H23 figures: employee benefits USD 0.541m + other operating expenses USD 0.859m","notes":"Source-backed adjusted recurring run-rate for the second half of 2023.","curated":true}'
FROM sources s
WHERE s.code = 'OTELLO_IR';

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-cost:2024-06-30:base',
    'ECONOMIC_NAV_COST_ANCHOR',
    'Economic NAV operating-cost anchor BASE from 2024-06-30',
    '2024-06-30T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/ZsWAp0aF0TcGJJNc_Report1H24.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-28.1","input_kind":"OPERATING_COST_ANCHOR","scenario":"BASE","effective_from":"2024-06-30","source_period":"1H24","source_period_start":"2024-01-01","source_period_end":"2024-06-30","period_days":182,"amount_usd":"1615000","source_measure":"employee benefits + other operating expenses, excluding depreciation and non-operational items","source_locator":"1H24 group performance: employee benefits USD 0.937m + other operating expenses USD 0.678m","notes":"Source-backed adjusted recurring run-rate for the first half of 2024.","curated":true}'
FROM sources s
WHERE s.code = 'OTELLO_IR';

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-cost:2024-12-31:base',
    'ECONOMIC_NAV_COST_ANCHOR',
    'Economic NAV operating-cost anchor BASE from 2024-12-31',
    '2024-12-31T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/Z7SFmZ7c43Q3f6lX_Report2H24.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-28.1","input_kind":"OPERATING_COST_ANCHOR","scenario":"BASE","effective_from":"2024-12-31","source_period":"2H24","source_period_start":"2024-07-01","source_period_end":"2024-12-31","period_days":184,"amount_usd":"958000","source_measure":"adjusted recurring employee benefits + other operating expenses","source_locator":"2H24 group performance: recurring employee benefits USD 0.479m + other operating expenses USD 0.479m; adjusted EBITDA USD -0.958m","notes":"Excludes the separately identified salary restructuring expense from the recurring investor run-rate.","curated":true}'
FROM sources s
WHERE s.code = 'OTELLO_IR';

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-cost:2025-06-30:base',
    'ECONOMIC_NAV_COST_ANCHOR',
    'Economic NAV operating-cost anchor BASE from 2025-06-30',
    '2025-06-30T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/aKa1FaTt2nPbajuo_Report1H25FINAL.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-28.1","input_kind":"OPERATING_COST_ANCHOR","scenario":"BASE","effective_from":"2025-06-30","source_period":"1H25","source_period_start":"2025-01-01","source_period_end":"2025-06-30","period_days":181,"amount_usd":"1286000","source_measure":"employee benefits + other operating expenses, excluding depreciation and non-operational items","source_locator":"1H25 group performance: employee benefits USD 0.643m + other operating expenses USD 0.643m","notes":"Source-backed adjusted recurring run-rate for the first half of 2025.","curated":true}'
FROM sources s
WHERE s.code = 'OTELLO_IR';

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-cost:2026-06-30:base',
    'ECONOMIC_NAV_COST_ANCHOR',
    'Economic NAV operating-cost anchor BASE from 2026-06-30',
    '2026-06-30T00:00:00Z',
    'https://financialfilings.com/filings/otello-corporation-asa/interim-quarterly-report/2026/57072581/',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-28.1","input_kind":"OPERATING_COST_ANCHOR","scenario":"BASE","effective_from":"2026-06-30","source_period":"1H26","source_period_start":"2026-01-01","source_period_end":"2026-06-30","period_days":181,"amount_usd":"1473000","source_measure":"employee benefits excluding stock compensation + other operating expenses","source_locator":"1H26 group performance: recurring employee benefits USD 0.687m excluding USD 0.418m stock compensation + other operating expenses USD 0.786m","notes":"Latest source-backed recurring run-rate for the investor overlay after the 1H26 report.","curated":true}'
FROM sources s
WHERE s.code = 'MANUAL';

-- Historical FULL snapshots before the 2025 option grant correctly contain a zero
-- option liability, but older rows pre-date the settlement metadata contract. Add the
-- explicit zero-option inputs so Estimated NAV history can evaluate these rows rather
-- than treating them as missing data.
UPDATE nav_snapshots
SET components_json = json_set(
    components_json,
    '$.other_net_assets.option_liability.inputs.before_grant', true,
    '$.other_net_assets.option_liability.inputs.option_count', 0,
    '$.other_net_assets.option_liability.inputs.gross_fair_value_nok', '0'
)
WHERE calculation_version = 'full-market-nav-daily-v2'
  AND nav_scope = 'FULL'
  AND substr(as_of_at, 1, 10) < '2025-09-15'
  AND json_valid(components_json);

UPDATE other_net_assets_daily_estimates
SET option_inputs_json = json_set(
    COALESCE(option_inputs_json, '{}'),
    '$.before_grant', true,
    '$.option_count', 0,
    '$.gross_fair_value_nok', '0'
)
WHERE estimate_date < '2025-09-15';
