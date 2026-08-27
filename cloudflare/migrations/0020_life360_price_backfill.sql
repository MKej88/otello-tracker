-- Backfill the late-July LIF closes needed by the 1M investor NAV view.
-- Values were manually verified against FinanceCharts and independently cross-checked
-- against StockAnalysis. Runtime repair remains Yahoo-first and Life360 IR/LSEG fallback.

INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes)
SELECT 'FINANCECHARTS', 'FinanceCharts historical market data', 'OTHER',
       'https://www.financecharts.com/', 0, 1,
       'Sekundær offentlig historikktabell brukt kun til eksplisitt kontrollert LIF-kursbackfill; ingen automatisert scraping.'
WHERE NOT EXISTS (SELECT 1 FROM sources WHERE code='FINANCECHARTS');

INSERT INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT s.id,
       'lif-financecharts-history-2026-07-27-2026-07-31',
       'MARKET_DATA_DERIVED_FILE',
       'Life360 LIF historical closes 27-31 July 2026',
       '2026-08-27T00:00:00Z',
       'https://www.financecharts.com/stocks/LIF/summary/price',
       '{"scope":"ONE_TIME_GAP_BACKFILL","source_quality":"SECONDARY_PUBLIC_HISTORY","symbol":"LIF","source_field":"Close","crosscheck":"https://stockanalysis.com/stocks/lif/history/"}'
FROM sources s
WHERE s.code='FINANCECHARTS'
  AND EXISTS (
      SELECT 1
      FROM market_prices mp
      JOIN instruments i ON i.id=mp.instrument_id
      WHERE i.symbol='LIF'
        AND i.exchange_mic='XNAS'
        AND mp.trading_date < '2026-07-27'
  )
  AND NOT EXISTS (
      SELECT 1 FROM source_documents sd
      WHERE sd.source_id=s.id
        AND sd.external_id='lif-financecharts-history-2026-07-27-2026-07-31'
  );

INSERT INTO market_prices(
    instrument_id, observed_at, trading_date, price_type, price, currency,
    source_id, source_document_id, quality, metadata_json
)
SELECT i.id, '2026-07-27T20:00:00Z', '2026-07-27', 'CLOSE', '53.83', 'USD',
       s.id, sd.id, 'RECONSTRUCTED',
       '{"backfill":"MANUALLY_VERIFIED_SECONDARY_HISTORY","source_field":"Close","crosscheck":"STOCKANALYSIS","price_semantics":"DAILY_CLOSE"}'
FROM instruments i
JOIN sources s ON s.code='FINANCECHARTS'
JOIN source_documents sd ON sd.source_id=s.id
    AND sd.external_id='lif-financecharts-history-2026-07-27-2026-07-31'
WHERE i.symbol='LIF' AND i.exchange_mic='XNAS'
  AND NOT EXISTS (
      SELECT 1 FROM market_prices existing
      WHERE existing.instrument_id=i.id
        AND existing.trading_date='2026-07-27'
        AND existing.source_id=s.id
        AND existing.price_type='CLOSE'
  );

INSERT INTO market_prices(
    instrument_id, observed_at, trading_date, price_type, price, currency,
    source_id, source_document_id, quality, metadata_json
)
SELECT i.id, '2026-07-28T20:00:00Z', '2026-07-28', 'CLOSE', '56.68', 'USD',
       s.id, sd.id, 'RECONSTRUCTED',
       '{"backfill":"MANUALLY_VERIFIED_SECONDARY_HISTORY","source_field":"Close","crosscheck":"STOCKANALYSIS","price_semantics":"DAILY_CLOSE"}'
FROM instruments i
JOIN sources s ON s.code='FINANCECHARTS'
JOIN source_documents sd ON sd.source_id=s.id
    AND sd.external_id='lif-financecharts-history-2026-07-27-2026-07-31'
WHERE i.symbol='LIF' AND i.exchange_mic='XNAS'
  AND NOT EXISTS (
      SELECT 1 FROM market_prices existing
      WHERE existing.instrument_id=i.id
        AND existing.trading_date='2026-07-28'
        AND existing.source_id=s.id
        AND existing.price_type='CLOSE'
  );

INSERT INTO market_prices(
    instrument_id, observed_at, trading_date, price_type, price, currency,
    source_id, source_document_id, quality, metadata_json
)
SELECT i.id, '2026-07-29T20:00:00Z', '2026-07-29', 'CLOSE', '55.29', 'USD',
       s.id, sd.id, 'RECONSTRUCTED',
       '{"backfill":"MANUALLY_VERIFIED_SECONDARY_HISTORY","source_field":"Close","crosscheck":"STOCKANALYSIS","price_semantics":"DAILY_CLOSE"}'
FROM instruments i
JOIN sources s ON s.code='FINANCECHARTS'
JOIN source_documents sd ON sd.source_id=s.id
    AND sd.external_id='lif-financecharts-history-2026-07-27-2026-07-31'
WHERE i.symbol='LIF' AND i.exchange_mic='XNAS'
  AND NOT EXISTS (
      SELECT 1 FROM market_prices existing
      WHERE existing.instrument_id=i.id
        AND existing.trading_date='2026-07-29'
        AND existing.source_id=s.id
        AND existing.price_type='CLOSE'
  );

INSERT INTO market_prices(
    instrument_id, observed_at, trading_date, price_type, price, currency,
    source_id, source_document_id, quality, metadata_json
)
SELECT i.id, '2026-07-30T20:00:00Z', '2026-07-30', 'CLOSE', '55.68', 'USD',
       s.id, sd.id, 'RECONSTRUCTED',
       '{"backfill":"MANUALLY_VERIFIED_SECONDARY_HISTORY","source_field":"Close","crosscheck":"STOCKANALYSIS","price_semantics":"DAILY_CLOSE"}'
FROM instruments i
JOIN sources s ON s.code='FINANCECHARTS'
JOIN source_documents sd ON sd.source_id=s.id
    AND sd.external_id='lif-financecharts-history-2026-07-27-2026-07-31'
WHERE i.symbol='LIF' AND i.exchange_mic='XNAS'
  AND NOT EXISTS (
      SELECT 1 FROM market_prices existing
      WHERE existing.instrument_id=i.id
        AND existing.trading_date='2026-07-30'
        AND existing.source_id=s.id
        AND existing.price_type='CLOSE'
  );

INSERT INTO market_prices(
    instrument_id, observed_at, trading_date, price_type, price, currency,
    source_id, source_document_id, quality, metadata_json
)
SELECT i.id, '2026-07-31T20:00:00Z', '2026-07-31', 'CLOSE', '54.05', 'USD',
       s.id, sd.id, 'RECONSTRUCTED',
       '{"backfill":"MANUALLY_VERIFIED_SECONDARY_HISTORY","source_field":"Close","crosscheck":"STOCKANALYSIS","price_semantics":"DAILY_CLOSE"}'
FROM instruments i
JOIN sources s ON s.code='FINANCECHARTS'
JOIN source_documents sd ON sd.source_id=s.id
    AND sd.external_id='lif-financecharts-history-2026-07-27-2026-07-31'
WHERE i.symbol='LIF' AND i.exchange_mic='XNAS'
  AND NOT EXISTS (
      SELECT 1 FROM market_prices existing
      WHERE existing.instrument_id=i.id
        AND existing.trading_date='2026-07-31'
        AND existing.source_id=s.id
        AND existing.price_type='CLOSE'
  );
