ALTER TABLE market_prices
    ADD COLUMN quality TEXT NOT NULL DEFAULT 'DIRECT'
    CHECK (quality IN ('DIRECT', 'RECONSTRUCTED'));

ALTER TABLE market_prices
    ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';

INSERT OR IGNORE INTO sources(code, name, source_type, base_url, is_official, terms_notes)
VALUES (
    'INVESTING',
    'Investing.com manual CSV export',
    'OTHER',
    'https://www.investing.com/',
    0,
    'Kun bruker-eksportert CSV til privat historisk backfill; ingen automatisert scraping. Pre-09.08.2022 OTEC-priser kan være dividend-adjusted og må rekonstrueres eksplisitt.'
);

CREATE INDEX idx_market_prices_quality ON market_prices(quality);
