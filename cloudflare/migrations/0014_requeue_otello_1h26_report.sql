-- Requeue only Otello result reports that were stopped by the previous v2 parser.
--
-- The 1H26 PDF introduced an explicit Note column before selected current-period values.
-- Parser v2 correctly failed closed and could therefore have left the NewsWeb row in
-- REVIEW_REQUIRED. Parser v3 understands that layout, so make those v2 parser failures
-- eligible for one new automatic attempt after this deployment.
--
-- Rows that failed for unrelated reasons (missing message id, network failure, manual review,
-- etc.) are deliberately not touched because they do not carry the v2 parser marker.

UPDATE company_news
SET processing_status = 'PARSED',
    notes = COALESCE(notes, '') ||
        '\nRequeued automatically for otello-financial-report-v3 after guarded v2 parser failure.',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE category = 'RESULTS'
  AND processing_status = 'REVIEW_REQUIRED'
  AND substr(COALESCE(published_at, ''), 1, 10) >= '2026-08-20'
  AND COALESCE(notes, '') LIKE '%otello-financial-report-v2%';
