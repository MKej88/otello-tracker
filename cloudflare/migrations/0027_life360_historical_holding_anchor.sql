-- Historical Life360 holding continuity anchor used only for investor attribution.
-- Otello reported approximately 0.05% ownership through the 2022-2024 annual reports,
-- while the FY2025 fair-value disclosure supports the 37,028 common-share anchor.
-- The historical count is therefore explicitly medium-confidence and must not be read
-- as an audited shareholder-register count or as an accounting NAV restatement.

-- Populated production D1 needs the Annual Report 2024 source document. Fresh bootstrap
-- databases get the canonical document and anchor from the curated SQLite import later.
INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'otello-annual-2024',
    'ANNUAL_REPORT',
    'Otello Corporation ASA - Annual Report 2024',
    '2025-04-25T00:00:00Z',
    'https://otello.cdn.prismic.io/otello/aBJT_PIqRLdaBwvK_otellocorporation-2024-12-31-en.pdf',
    '{"life360_holdings_manifest_version":"2026-08-30.1","curated":true,"extraction_method_detail":"CONTINUITY_DERIVED_MEDIUM_CONFIDENCE"}'
FROM sources s
WHERE s.code='OTELLO_IR'
  AND EXISTS (SELECT 1 FROM nav_snapshots LIMIT 1);

INSERT OR IGNORE INTO life360_holding_anchors(
    effective_from, effective_to, shares, quality, basis,
    source_document_id, source_locator, notes
)
SELECT
    '2022-12-31',
    '2025-12-30',
    37028,
    'DERIVED_MEDIUM_CONFIDENCE',
    'CONTINUITY_DERIVED_FROM_REPORTED_OWNERSHIP_AND_2025_FAIR_VALUE',
    sd.id,
    'Annual Reports 2022-2024 report approximately 0.05% ownership in Life360; 37,028 common shares is carried backward from the 2025 fair-value-derived holding because no disposal or change in the Life360 position is disclosed over the period; attribution assumption only',
    'Historical share count is an attribution assumption, not an explicitly reported shareholder-register count. Use only for historical investor attribution; do not treat it as audited exact ownership or as an accounting NAV restatement.'
FROM source_documents sd
JOIN sources s ON s.id=sd.source_id
WHERE s.code='OTELLO_IR'
  AND sd.external_id='otello-annual-2024'
ORDER BY sd.id DESC
LIMIT 1;

INSERT INTO provenance_records(
    entity_table, entity_id, field_name, source_document_id,
    source_locator, extraction_method, confidence, extracted_value
)
SELECT
    'life360_holding_anchors',
    h.id,
    'shares',
    h.source_document_id,
    h.source_locator,
    'CALCULATED',
    'MEDIUM',
    CAST(h.shares AS TEXT)
FROM life360_holding_anchors h
WHERE h.effective_from='2022-12-31'
  AND NOT EXISTS (
      SELECT 1
      FROM provenance_records p
      WHERE p.entity_table='life360_holding_anchors'
        AND p.entity_id=h.id
        AND p.field_name='shares'
        AND p.source_document_id=h.source_document_id
        AND COALESCE(p.source_locator, '')=COALESCE(h.source_locator, '')
        AND COALESCE(p.extracted_value, '')=CAST(h.shares AS TEXT)
  );
