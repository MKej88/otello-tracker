-- Life360 market-data reference identities. Yahoo Finance is a pragmatic secondary
-- machine-readable source; Life360 IR/Nasdaq remain the human control sources.
INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes) VALUES
    ('YAHOO_FINANCE', 'Yahoo Finance', 'API', 'https://query1.finance.yahoo.com/', 0, 1, 'Sekundær, uoffisiell maskinlesbar kurskilde. Siste gode verdi beholdes ved kildefeil; rå svar arkiveres med proveniens.')
ON CONFLICT(code) DO UPDATE SET
    name=excluded.name,
    source_type=excluded.source_type,
    base_url=excluded.base_url,
    is_official=excluded.is_official,
    is_active=excluded.is_active,
    terms_notes=excluded.terms_notes;

INSERT INTO instruments(symbol, name, asset_type, exchange_mic, currency, isin, source_symbol, is_active) VALUES
    ('LIF', 'Life360, Inc. common stock', 'EQUITY', 'XNAS', 'USD', NULL, 'LIF', 1),
    ('360.AX', 'Life360, Inc. CHESS Depositary Interests', 'EQUITY', 'XASX', 'AUD', NULL, '360.AX', 1)
ON CONFLICT(symbol, exchange_mic) DO UPDATE SET
    name=excluded.name,
    asset_type=excluded.asset_type,
    currency=excluded.currency,
    isin=excluded.isin,
    source_symbol=excluded.source_symbol,
    is_active=excluded.is_active;
