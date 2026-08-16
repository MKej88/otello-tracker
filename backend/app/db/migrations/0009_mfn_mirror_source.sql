INSERT INTO sources(
    code, name, source_type, base_url, is_official, is_active, terms_notes
) VALUES (
    'MFN',
    'MFN.se',
    'OTHER',
    'https://mfn.se',
    0,
    1,
    'Secondary public mirror/discovery source. Never label as official; upstream provider/source must be retained in document metadata.'
)
ON CONFLICT(code) DO UPDATE SET
    name = excluded.name,
    source_type = excluded.source_type,
    base_url = excluded.base_url,
    is_official = excluded.is_official,
    is_active = excluded.is_active,
    terms_notes = excluded.terms_notes;
