-- Reference identity for backend migration 0027.
-- Keep this source-only so fresh D1 bootstrap targets can establish the same stable
-- source id as SQLite before importing historical data.

INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes)
SELECT 'FT_MARKETS', 'Financial Times Markets historical data', 'OTHER',
       'https://markets.ft.markitdigital.com/', 0, 1,
       'Sekundær offentlig historikktabell brukt kun til eksplisitt kontrollert OTEC-volum-backfill; ingen automatisert scraping.'
WHERE NOT EXISTS (SELECT 1 FROM sources WHERE code='FT_MARKETS');
