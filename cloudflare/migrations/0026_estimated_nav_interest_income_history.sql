-- Backfill source-backed cash-interest history used by the 3-year Estimated NAV view.
-- Fresh databases receive the same canonical rows from the deterministic history bootstrap;
-- this migration only repairs already-populated production/local D1 databases.

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-interest:2H23',
    'ECONOMIC_NAV_INTEREST_INCOME_ANCHOR',
    'Economic NAV interest-income anchor 2H23',
    '2023-12-31T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/e31bfa91-f47c-4200-876c-20bd15bfdefd_2H%2B2023%2Bcompiled%2Breport.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-30.2","input_kind":"INTEREST_INCOME_ANCHOR","source_period":"2H23","source_period_start":"2023-07-01","source_period_end":"2023-12-31","period_days":184,"amount_usd":"400000","source_measure":"interest returns on cash position (reported rounded half-year amount)","source_locator":"2H23 net-financial-items discussion reports interest returns on the cash position of USD 0.4 million.","source_precision":"ROUNDED_TO_USD_0_1M","fx_segments":[{"start_date":"2023-07-01","end_date":"2023-09-30","usd_nok":"10.7254","source_label":"For the September period 2023"},{"start_date":"2023-10-01","end_date":"2023-12-31","usd_nok":"10.5266","source_label":"For the December period 2023"}],"notes":"The published 2H23 report states USD 0.4m rather than a thousand-dollar cash-flow amount. The anchor therefore preserves that source precision and must be treated as approximate.","curated":true,"attribution_policy":"REPORTED_HALF_YEAR_INTEREST_PRORATED_BY_DAY_USING_REPORTED_PERIOD_FX"}'
FROM sources s
WHERE s.code = 'OTELLO_IR'
  AND EXISTS (SELECT 1 FROM nav_snapshots LIMIT 1);

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-interest:1H24',
    'ECONOMIC_NAV_INTEREST_INCOME_ANCHOR',
    'Economic NAV interest-income anchor 1H24',
    '2024-06-30T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/aKa1FaTt2nPbajuo_Report1H25FINAL.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-30.2","input_kind":"INTEREST_INCOME_ANCHOR","source_period":"1H24","source_period_start":"2024-01-01","source_period_end":"2024-06-30","period_days":182,"amount_usd":"413000","source_measure":"interest income received","source_locator":"1H25 consolidated cash-flow comparative column reports 1H24 Interest income received of USD 413 thousand; 1H24 report provides the period USD/NOK rates.","fx_segments":[{"start_date":"2024-01-01","end_date":"2024-03-31","usd_nok":"10.6167","source_label":"For the March period 2024","source_url":"https://otello.cdn.prismic.io/otello/ZsWAp0aF0TcGJJNc_Report1H24.pdf"},{"start_date":"2024-04-01","end_date":"2024-06-30","usd_nok":"10.6125","source_label":"For the June period 2024","source_url":"https://otello.cdn.prismic.io/otello/ZsWAp0aF0TcGJJNc_Report1H24.pdf"}],"notes":"Exact cash-interest amount is taken from the later official comparative cash-flow disclosure; period FX is taken from the contemporaneous 1H24 report.","curated":true,"attribution_policy":"REPORTED_HALF_YEAR_INTEREST_PRORATED_BY_DAY_USING_REPORTED_PERIOD_FX"}'
FROM sources s
WHERE s.code = 'OTELLO_IR'
  AND EXISTS (SELECT 1 FROM nav_snapshots LIMIT 1);

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-interest:2H24',
    'ECONOMIC_NAV_INTEREST_INCOME_ANCHOR',
    'Economic NAV interest-income anchor 2H24',
    '2024-12-31T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/aBJT_PIqRLdaBwvK_otellocorporation-2024-12-31-en.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-30.2","input_kind":"INTEREST_INCOME_ANCHOR","source_period":"2H24","source_period_start":"2024-07-01","source_period_end":"2024-12-31","period_days":184,"amount_usd":"425000","source_measure":"interest income received (derived from audited FY less reported 1H)","source_locator":"Annual Report 2024 cash flow reports FY2024 Interest income received USD 838 thousand; official 1H25 comparative reports 1H24 USD 413 thousand; 2H24 is therefore USD 425 thousand.","fx_segments":[{"start_date":"2024-07-01","end_date":"2024-09-30","usd_nok":"10.6121","source_label":"For the September period 2024","source_url":"https://otello.cdn.prismic.io/otello/Z7SFmZ7c43Q3f6lX_Report2H24.pdf"},{"start_date":"2024-10-01","end_date":"2024-12-31","usd_nok":"11.1988","source_label":"For the December period 2024","source_url":"https://otello.cdn.prismic.io/otello/Z7SFmZ7c43Q3f6lX_Report2H24.pdf"}],"notes":"Derived exact half-year cash receipt: audited FY2024 cash interest less the exact 1H24 comparative cash-interest amount.","curated":true,"attribution_policy":"REPORTED_HALF_YEAR_INTEREST_PRORATED_BY_DAY_USING_REPORTED_PERIOD_FX"}'
FROM sources s
WHERE s.code = 'OTELLO_IR'
  AND EXISTS (SELECT 1 FROM nav_snapshots LIMIT 1);

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-interest:1H25',
    'ECONOMIC_NAV_INTEREST_INCOME_ANCHOR',
    'Economic NAV interest-income anchor 1H25',
    '2025-06-30T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/aKa1FaTt2nPbajuo_Report1H25FINAL.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-30.2","input_kind":"INTEREST_INCOME_ANCHOR","source_period":"1H25","source_period_start":"2025-01-01","source_period_end":"2025-06-30","period_days":181,"amount_usd":"537000","source_measure":"interest income received","source_locator":"1H25 consolidated cash-flow statement: Interest income received USD 537 thousand.","fx_segments":[{"start_date":"2025-01-01","end_date":"2025-03-31","usd_nok":"10.6867","source_label":"For the March period 2025"},{"start_date":"2025-04-01","end_date":"2025-06-30","usd_nok":"10.0577","source_label":"For the June period 2025"}],"notes":"Reported half-year cash interest allocated evenly by calendar day and translated using Otello''s reported USD/NOK period rates.","curated":true,"attribution_policy":"REPORTED_HALF_YEAR_INTEREST_PRORATED_BY_DAY_USING_REPORTED_PERIOD_FX"}'
FROM sources s
WHERE s.code = 'OTELLO_IR'
  AND EXISTS (SELECT 1 FROM nav_snapshots LIMIT 1);
