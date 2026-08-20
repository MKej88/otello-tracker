INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes) VALUES
    ('NORGES_BANK', 'Norges Bank', 'API', 'https://data.norges-bank.no/', 1, 1,
     'Primærkilde for daglige NOK-valutakurser. Åpent offentlig API; BRL/NOK og USD/NOK hentes direkte uten EUR-kryss.')
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    source_type = excluded.source_type,
    base_url = excluded.base_url,
    is_official = excluded.is_official,
    is_active = excluded.is_active,
    terms_notes = excluded.terms_notes;
