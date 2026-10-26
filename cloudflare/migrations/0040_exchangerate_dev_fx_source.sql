-- Staged source only. Disabled in production pending permission for existing
-- public API redistribution of both raw and derived BRL/NOK data.
INSERT INTO sources(code, name, source_type, base_url, is_official, is_active, terms_notes)
VALUES (
  'EXCHANGERATE_DEV', 'Exchangerate.dev indicative BRL/NOK',
  'API', 'https://api.exchangerate.dev/', 0, 1,
  'Indicative, typically 15-minute delayed cross quote. Do not enable without written permission for redistribution via public OtelloTracker API endpoints; Free also requires visible linked attribution. Historical/official FX remains Norges Bank.'
)
ON CONFLICT(code) DO UPDATE SET
  name = excluded.name,
  source_type = excluded.source_type,
  base_url = excluded.base_url,
  is_official = excluded.is_official,
  terms_notes = excluded.terms_notes;
