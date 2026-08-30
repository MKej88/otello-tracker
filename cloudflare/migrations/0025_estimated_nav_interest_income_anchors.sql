-- Source-backed cash-interest anchors for Estimated NAV history.
-- Existing populated D1 databases need these rows immediately; fresh databases
-- receive the same canonical inputs from the deterministic history bootstrap.

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-interest:2H25',
    'ECONOMIC_NAV_INTEREST_INCOME_ANCHOR',
    'Economic NAV interest-income anchor 2H25',
    '2025-12-31T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/aZVvCFWLo0XkEnNV_2H25_report.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-30.1","input_kind":"INTEREST_INCOME_ANCHOR","source_period":"2H25","source_period_start":"2025-07-01","source_period_end":"2025-12-31","period_days":184,"amount_usd":"339000","source_measure":"interest income received","source_locator":"2H25 consolidated cash-flow statement: Interest income received USD 339 thousand; group-performance section confirms interest income of USD 339 thousand.","fx_segments":[{"start_date":"2025-07-01","end_date":"2025-09-30","usd_nok":"9.9474","source_label":"For the September period 2025"},{"start_date":"2025-10-01","end_date":"2025-12-31","usd_nok":"10.1196","source_label":"For the December period 2025"}],"notes":"Reported half-year cash interest. Arbitrary NAV-history windows allocate the USD amount evenly by calendar day and use Otello reported USD/NOK period rates.","curated":true,"attribution_policy":"REPORTED_HALF_YEAR_INTEREST_PRORATED_BY_DAY_USING_REPORTED_PERIOD_FX"}'
FROM sources s
WHERE s.code = 'OTELLO_IR'
  AND EXISTS (SELECT 1 FROM nav_snapshots LIMIT 1);

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'economic-nav-interest:1H26',
    'ECONOMIC_NAV_INTEREST_INCOME_ANCHOR',
    'Economic NAV interest-income anchor 1H26',
    '2026-06-30T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/RlJbV0szFAaAhxyB_Report1H26FINAL.pdf',
    '{"economic_nav_input_version":"economic-nav-inputs-2026-08-30.1","input_kind":"INTEREST_INCOME_ANCHOR","source_period":"1H26","source_period_start":"2026-01-01","source_period_end":"2026-06-30","period_days":181,"amount_usd":"326000","source_measure":"interest income received","source_locator":"1H26 consolidated cash-flow statement: Interest income received USD 326 thousand; report states operating cash flow was affected by lower interest income received.","fx_segments":[{"start_date":"2026-01-01","end_date":"2026-03-31","usd_nok":"9.6605","source_label":"For the March period 2026"},{"start_date":"2026-04-01","end_date":"2026-06-30","usd_nok":"9.5815","source_label":"For the June period 2026"}],"notes":"Reported half-year cash interest. Arbitrary NAV-history windows allocate the USD amount evenly by calendar day and use Otello reported USD/NOK period rates.","curated":true,"attribution_policy":"REPORTED_HALF_YEAR_INTEREST_PRORATED_BY_DAY_USING_REPORTED_PERIOD_FX"}'
FROM sources s
WHERE s.code = 'OTELLO_IR'
  AND EXISTS (SELECT 1 FROM nav_snapshots LIMIT 1);
