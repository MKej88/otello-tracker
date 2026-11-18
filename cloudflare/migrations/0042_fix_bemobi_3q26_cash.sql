-- One-time, source-evidenced correction of the 3Q26 year-as-cash parser bug.
-- The issuer's Earnings Release 3Q26 (12 November 2026) explicitly states:
-- "cash position remains solid (R$319 million at the end of 3Q26)".
-- Source (issuer release mirrored without edits by Publicnow):
-- https://www.marketscreener.com/news/earnings-release-3q26-2026-11-12t00-00-00-000z-ce785ed9dd8dfe21
--
-- 2025 was misread as 2,025m BRL. Update ONLY matching 3Q26 official RESULT
-- facts with the observed defect and cross-checked revenue/EBITDA. Never
-- modify NAV snapshots, other quarters, source-document links or cash models.
-- Once the corrected PDF parser runs, future updates are source driven.
UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.cash_mbrl', 319.0,
        '$.cash_quality', 'OFFICIAL_REPORTED',
        '$.cash_correction_source_url',
          'https://www.marketscreener.com/news/earnings-release-3q26-2026-11-12t00-00-00-000z-ce785ed9dd8dfe21',
        '$.cash_correction_note',
          'One-time verified repair: FY2025 incorrectly parsed as R$2,025m; 3Q26 issuer release explicitly reports R$319m.'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE fact_type = 'RESULT'
  AND fact_key = '3Q26'
  AND as_of_date = '2026-09-30'
  AND source_name IN ('BEMOBI_IR', 'CVM')
  AND CAST(json_extract(payload_json, '$.cash_mbrl') AS REAL) BETWEEN 2024 AND 2026
  AND CAST(json_extract(payload_json, '$.adjusted_net_revenue_mbrl') AS REAL) BETWEEN 244 AND 246
  AND CAST(json_extract(payload_json, '$.adjusted_ebitda_mbrl') AS REAL) BETWEEN 85 AND 89;
