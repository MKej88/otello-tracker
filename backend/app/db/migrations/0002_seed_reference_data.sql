INSERT OR IGNORE INTO sources(code, name, source_type, base_url, is_official, terms_notes) VALUES
    ('OTELLO_IR', 'Otello Corporation Investor Relations', 'IR', 'https://www.otellocorp.com/', 1, 'Primærkilde for Otello-rapporter og selskapsinformasjon.'),
    ('EURONEXT', 'Euronext', 'EXCHANGE', 'https://live.euronext.com/', 1, 'Primær børs-/meldingskilde for OTEC der bruksvilkår tillater automatisering.'),
    ('BEMOBI_IR', 'Bemobi Investor Relations', 'IR', 'https://ri.bemobi.com.br/', 1, 'Primærkilde for Bemobi-resultater, utbytte/JCP og selskapsmeldinger.'),
    ('CVM', 'Comissão de Valores Mobiliários', 'REGULATOR', 'https://www.gov.br/cvm/', 1, 'Brasiliansk regulatorisk primærkilde.'),
    ('B3', 'B3 - Brasil Bolsa Balcão', 'EXCHANGE', 'https://www.b3.com.br/', 1, 'Primærkilde for brasiliansk markedshistorikk og corporate actions.'),
    ('ECB', 'European Central Bank', 'API', 'https://data.ecb.europa.eu/', 1, 'Primærkilde for daglige valutareferansekurser.'),
    ('BRAPI', 'brapi.dev', 'API', 'https://brapi.dev/', 0, 'Sekundær API-kilde for løpende brasilianske kurser.'),
    ('EODHD', 'EOD Historical Data', 'API', 'https://eodhd.com/', 0, 'Sekundær kilde for end-of-day markedsdata.'),
    ('MANUAL', 'Manuell registrering', 'MANUAL', NULL, 0, 'Brukes bare når datapunktet er manuelt kontrollert og dokumentert.');

INSERT OR IGNORE INTO instruments(symbol, name, asset_type, exchange_mic, currency, isin, source_symbol) VALUES
    ('OTEC', 'Otello Corporation ASA', 'EQUITY', 'XOSL', 'NOK', 'NO0010040611', 'OTEC'),
    ('BMOB3', 'Bemobi Mobile Tech S.A.', 'EQUITY', 'BVMF', 'BRL', NULL, 'BMOB3');
