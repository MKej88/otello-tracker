-- Production D1 equivalent of backend migration 0027.
-- Gap rows are explicitly secondary, manually verified FT Markets history. New runtime
-- activity is ingested from Euronext's official delayed trade files.

INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes)
SELECT 'FT_MARKETS', 'Financial Times Markets historical data', 'OTHER',
       'https://markets.ft.markitdigital.com/', 0, 1,
       'Sekundær offentlig historikktabell brukt kun til eksplisitt kontrollert OTEC-volum-backfill; ingen automatisert scraping.'
WHERE NOT EXISTS (SELECT 1 FROM sources WHERE code='FT_MARKETS');

INSERT INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT s.id,
       'otec-ft-history-2026-08-17-2026-08-24',
       'MARKET_DATA_DERIVED_FILE',
       'OTEC historical daily activity 17-24 August 2026',
       '2026-08-24T23:59:59Z',
       'https://markets.ft.markitdigital.com/data/equities/tearsheet/historical?s=OTEC:OSL',
       '{"scope":"ONE_TIME_GAP_BACKFILL","source_quality":"SECONDARY_PUBLIC_HISTORY","symbol":"OTEC","volume_field":"Volume"}'
FROM sources s
WHERE s.code='FT_MARKETS'
  AND NOT EXISTS (
      SELECT 1 FROM source_documents sd
      WHERE sd.source_id=s.id AND sd.external_id='otec-ft-history-2026-08-17-2026-08-24'
  );

INSERT INTO market_activity(
    instrument_id, trading_date, volume_shares, last_price_nok,
    source_id, source_document_id, quality, metadata_json
)
SELECT i.id, v.trading_date, v.volume_shares, v.last_price_nok,
       s.id, sd.id, 'HISTORICAL_EXPORT',
       '{"backfill":"MANUALLY_VERIFIED_SECONDARY_HISTORY","source_field":"Volume","preferred_runtime_source":"EURONEXT"}'
FROM (
    SELECT '2026-08-17' AS trading_date, 53546 AS volume_shares, '17.50' AS last_price_nok
    UNION ALL SELECT '2026-08-18', 31690, '17.36'
    UNION ALL SELECT '2026-08-19', 59082, '17.20'
    UNION ALL SELECT '2026-08-20', 37050, '17.00'
    UNION ALL SELECT '2026-08-21', 76185, '17.04'
    UNION ALL SELECT '2026-08-24', 61091, '16.94'
) v
JOIN instruments i ON i.symbol='OTEC' AND i.exchange_mic='XOSL'
JOIN sources s ON s.code='FT_MARKETS'
JOIN source_documents sd ON sd.source_id=s.id
    AND sd.external_id='otec-ft-history-2026-08-17-2026-08-24'
WHERE NOT EXISTS (
    SELECT 1 FROM market_activity existing
    WHERE existing.instrument_id=i.id AND existing.trading_date=v.trading_date
);

INSERT INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT s.id,
       'otec-buyback-program-2026-06-08-max-price',
       'REGULATORY_NEWS',
       'Otello Corporation - Share Buyback Program',
       '2026-06-08T00:00:00Z',
       'https://live.euronext.com/en/products/equities/company-news/2026-06-08-share-buyback-program',
       '{"field":"max_price_nok","value":"20","source_quality":"OFFICIAL_EURONEXT_DISCLOSURE"}'
FROM sources s
WHERE s.code='EURONEXT'
  AND NOT EXISTS (
      SELECT 1 FROM source_documents sd
      WHERE sd.source_id=s.id AND sd.external_id='otec-buyback-program-2026-06-08-max-price'
  );

UPDATE buyback_programs
SET max_price_nok='20'
WHERE max_price_nok IS NULL
  AND start_date='2026-06-08'
  AND max_shares=2192046;

INSERT INTO provenance_records(
    entity_table, entity_id, field_name, source_document_id,
    source_locator, extraction_method, confidence, extracted_value
)
SELECT 'buyback_programs', p.id, 'max_price_nok', sd.id,
       'Maximum consideration sentence in 8 June 2026 Share Buyback Program',
       'MANUAL', 'HIGH', '20'
FROM buyback_programs p
JOIN sources s ON s.code='EURONEXT'
JOIN source_documents sd ON sd.source_id=s.id
    AND sd.external_id='otec-buyback-program-2026-06-08-max-price'
WHERE p.start_date='2026-06-08'
  AND p.max_shares=2192046
  AND p.max_price_nok='20'
  AND NOT EXISTS (
      SELECT 1 FROM provenance_records pr
      WHERE pr.entity_table='buyback_programs'
        AND pr.entity_id=p.id
        AND pr.field_name='max_price_nok'
        AND pr.source_document_id=sd.id
  );
