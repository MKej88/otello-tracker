-- Independent fallback for the NAV-critical Life360 LIF close. The page is published
-- by Life360 Investor Relations; the delayed/historical market data is supplied by LSEG.
INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes) VALUES
    (
        'LIFE360_IR_LSEG',
        'Life360 IR / LSEG',
        'IR',
        'https://investors.life360.com/',
        0,
        1,
        'Uavhengig sekundær fallback for LIF-sluttkurs. Publiseres på Life360 Investor Relations med LSEG som datakilde. Brukes bare når begge Yahoo-endepunkter feiler; maks 7 dager gammel kurs.'
    )
ON CONFLICT(code) DO UPDATE SET
    name=excluded.name,
    source_type=excluded.source_type,
    base_url=excluded.base_url,
    is_official=excluded.is_official,
    is_active=excluded.is_active,
    terms_notes=excluded.terms_notes;
