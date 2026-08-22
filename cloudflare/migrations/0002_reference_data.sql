-- Cloudflare D1 reference data equivalent to backend migrations 0002/0007/0009/0013.
-- Financial/history data is migrated separately; this file only establishes stable source
-- and instrument identities required by the application.

INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes) VALUES
    ('OTELLO_IR', 'Otello Corporation Investor Relations', 'IR', 'https://www.otellocorp.com/', 1, 1, 'Primærkilde for Otello-rapporter og selskapsinformasjon.'),
    ('EURONEXT', 'Euronext', 'EXCHANGE', 'https://live.euronext.com/', 1, 1, 'Primær børs-/meldingskilde for OTEC der bruksvilkår tillater automatisering.'),
    ('BEMOBI_IR', 'Bemobi Investor Relations', 'IR', 'https://ri.bemobi.com.br/', 1, 1, 'Primærkilde for Bemobi-resultater, utbytte/JCP og selskapsmeldinger.'),
    ('CVM', 'Comissão de Valores Mobiliários', 'REGULATOR', 'https://www.gov.br/cvm/', 1, 1, 'Brasiliansk regulatorisk primærkilde.'),
    ('B3', 'B3 - Brasil Bolsa Balcão', 'EXCHANGE', 'https://www.b3.com.br/', 1, 1, 'Primærkilde for brasiliansk markedshistorikk og corporate actions.'),
    ('ECB', 'European Central Bank', 'API', 'https://data.ecb.europa.eu/', 1, 1, 'Primærkilde for daglige valutareferansekurser.'),
    ('BRAPI', 'brapi.dev', 'API', 'https://brapi.dev/', 0, 1, 'Sekundær API-kilde for løpende brasilianske kurser.'),
    ('EODHD', 'EOD Historical Data', 'API', 'https://eodhd.com/', 0, 1, 'Sekundær kilde for end-of-day markedsdata.'),
    ('MANUAL', 'Manuell registrering', 'MANUAL', NULL, 0, 1, 'Brukes bare når datapunktet er manuelt kontrollert og dokumentert.'),
    ('INVESTING', 'Investing.com manual CSV export', 'OTHER', 'https://www.investing.com/', 0, 1, 'Kun bruker-eksportert CSV til privat historisk backfill; ingen automatisert scraping. Pre-09.08.2022 OTEC-priser kan være dividend-adjusted og må rekonstrueres eksplisitt.'),
    ('MFN', 'MFN.se', 'OTHER', 'https://mfn.se', 0, 1, 'Secondary public mirror/discovery source. Never label as official; upstream provider/source must be retained in document metadata.'),
    ('NEWSWEB', 'Oslo Børs NewsWeb', 'EXCHANGE', 'https://newsweb.oslobors.no/', 1, 1, 'Official Oslo Børs disclosure and attachment source. Store only OTEC-relevant facts/metadata needed for private research and provenance.')
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    source_type = excluded.source_type,
    base_url = excluded.base_url,
    is_official = excluded.is_official,
    is_active = excluded.is_active,
    terms_notes = excluded.terms_notes;

INSERT INTO instruments(symbol, name, asset_type, exchange_mic, currency, isin, source_symbol, is_active) VALUES
    ('OTEC', 'Otello Corporation ASA', 'EQUITY', 'XOSL', 'NOK', 'NO0010040611', 'OTEC', 1),
    ('BMOB3', 'Bemobi Mobile Tech S.A.', 'EQUITY', 'BVMF', 'BRL', NULL, 'BMOB3', 1)
ON CONFLICT(symbol, exchange_mic) DO UPDATE SET
    name = excluded.name,
    asset_type = excluded.asset_type,
    currency = excluded.currency,
    isin = excluded.isin,
    source_symbol = excluded.source_symbol,
    is_active = excluded.is_active;
