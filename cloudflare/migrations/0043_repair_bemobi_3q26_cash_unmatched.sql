-- Follow-up to 0042: D1 applied the migration successfully, but the live
-- dashboard still rejected cash for 3Q26. Migration success is NOT evidence
-- that the previous guarded UPDATE matched the production fact row.
--
-- Official issuer 3Q26 Earnings Release (12 Nov 2026): ending cash R$319m.
-- https://www.marketscreener.com/news/earnings-release-3q26-2026-11-12t00-00-00-000z-ce785ed9dd8dfe21
--
-- One FACT row is uniquely identified as 3Q26 RESULT, regardless of source
-- display name, whether as_of_date is empty, or rounded KPI values. Never
-- replace a valid already reported cash amount (e.g. precise R$319.3m).
-- Only correct missing or clearly invalid cash values.
UPDATE bemobi_investor_facts
SET payload_json = json_set(
        payload_json,
        '$.cash_mbrl', 319.0,
        '$.cash_quality', 'OFFICIAL_REPORTED',
        '$.cash_correction_source_url',
          'https://www.marketscreener.com/news/earnings-release-3q26-2026-11-12t00-00-00-000z-ce785ed9dd8dfe21',
        '$.cash_correction_note',
          'Confirmed 3Q26 ending cash R$319m (issuer earnings release 12 Nov 2026); replaced missing/invalid parser value.'
    ),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE fact_type = 'RESULT'
  -- The report's own period is authoritative for this one-off correction.
  -- Neither fact_key nor as_of_date is guaranteed to be populated consistently.
  AND json_extract(payload_json, '$.period') = '3Q26'
  AND (
    json_extract(payload_json, '$.cash_mbrl') IS NULL
    OR CAST(json_extract(payload_json, '$.cash_mbrl') AS REAL) NOT BETWEEN 10 AND 1500
  );
