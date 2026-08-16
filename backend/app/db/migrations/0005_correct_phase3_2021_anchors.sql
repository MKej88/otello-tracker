-- Phase 3 initially used conservative placeholders for two 2021 gaps and
-- attached two share-cancellation quantities to the wrong event dates.
-- Remove only the exact curated rows so the corrected manifest can reseed them.

DELETE FROM provenance_records
WHERE entity_table = 'bemobi_holdings'
  AND entity_id IN (
      SELECT id FROM bemobi_holdings
      WHERE effective_from = '2022-06-30'
        AND shares = 32719588
  );

DELETE FROM bemobi_holdings
WHERE effective_from = '2022-06-30'
  AND shares = 32719588;

DELETE FROM provenance_records
WHERE entity_table = 'corporate_actions'
  AND entity_id IN (
      SELECT ca.id
      FROM corporate_actions ca
      JOIN instruments i ON i.id = ca.issuer_instrument_id
      WHERE i.symbol = 'OTEC'
        AND ca.action_type = 'SHARE_CANCELLATION'
        AND (
            (ca.announcement_date = '2021-09-30' AND ca.quantity = 11200000)
            OR
            (ca.announcement_date = '2022-01-27' AND ca.quantity = 9999998)
        )
  );

DELETE FROM corporate_actions
WHERE id IN (
    SELECT ca.id
    FROM corporate_actions ca
    JOIN instruments i ON i.id = ca.issuer_instrument_id
    WHERE i.symbol = 'OTEC'
      AND ca.action_type = 'SHARE_CANCELLATION'
      AND (
          (ca.announcement_date = '2021-09-30' AND ca.quantity = 11200000)
          OR
          (ca.announcement_date = '2022-01-27' AND ca.quantity = 9999998)
      )
);
