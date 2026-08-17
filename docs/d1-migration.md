# D1-migrering, schema parity og data parity

Phase 15 etablerer databasestrukturen og dataflyttingen for Cloudflare-produksjonen. Målet er at D1 skal ha samme strukturelle og finansielle semantikk som den validerte SQLite-referansen før API/jobber flyttes.

## Prinsipp

Vi vedlikeholder **ikke** et håndkopiert D1-schema parallelt med backend-migreringene.

`cloudflare/tools/generate_d1_schema.py` gjør i stedet dette:

1. oppretter en tom midlertidig SQLite-database;
2. kjører alle backend-migreringene gjennom siste versjon;
3. leser den effektive sluttilstanden fra `sqlite_master`;
4. eksporterer tabeller, eksplisitte indekser og triggere;
5. utelater backendens `schema_migrations`, fordi Wrangler/D1 fører sin egen migreringshistorikk;
6. skriver `cloudflare/migrations/0001_initial_schema.sql`.

Dermed er backendens migrerte schema fortsatt referansen under overgangsperioden, mens D1-schemaet er en deterministisk konsolidert representasjon av samme struktur.

## D1-migreringer

```text
cloudflare/migrations/
  0001_initial_schema.sql   # generert sluttschema
  0002_reference_data.sql   # stabile sources/instruments
```

`0001` skal aldri redigeres manuelt. Endres backend-schemaet før D1 er produksjonsmaster, regenereres filen:

```bash
python cloudflare/tools/generate_d1_schema.py
```

CI bruker:

```bash
python cloudflare/tools/generate_d1_schema.py --check
```

og feiler dersom den committede D1-filen har driftet fra referanseschemaet.

## Foreign keys

D1 håndhever foreign keys. Det genererte bootstrap-schemaet bruker derfor `defer_foreign_keys` under opprettelse/import. Finansielle relasjoner, `ON DELETE`-regler og øvrige constraints beholdes, og både schema- og dataparitet avsluttes med `PRAGMA foreign_key_check`.

## Schema parity – Phase 15.1

`backend/tests/test_d1_schema_parity.py` oppretter to tomme databaser:

- **reference:** alle ordinære backend-migreringer til siste versjon;
- **D1-shape:** det konsoliderte D1-schemaet.

Testene sammenligner:

- eksakt tabellsett;
- kolonnenavn, type, `NOT NULL`, default og primary-key-posisjon;
- foreign keys og delete/update-regler;
- eksplisitte indekser, uniqueness, partial-index flagg og kolonner;
- triggere;
- stabile source-/instrumentreferanser;
- `PRAGMA foreign_key_check`;
- NewsWeb-triggeradferd som beskytter provenance/klassifisering.

## Data parity – Phase 15.2

Phase 15.2 er implementert som en separat, repeterbar bootstrap-pipeline. Den tar en validert SQLite-snapshot og lager:

```text
bootstrap.sql
manifest.json
```

Manifestet inneholder radtall, kolonneorden og logisk SHA-256 per relevant tabell, samt én global SHA-256 og finansielle kontrollpunkter for CORE/FULL NAV, market/FX coverage, cash, ONA, share count, Bemobi-holding og buybacks.

`sources` og `instruments` opprettes fortsatt av `0002_reference_data.sql`, men bootstrapen bevarer og kontrollerer ID-er og de opprinnelige migreringsmetadataene slik at D1-snapshoten blir logisk identisk med SQLite-kilden.

Historisk finans-/markedsdata flyttes; gamle runtime-tabeller (`job_runs`, `source_health`, `runtime_state`) resettes med vilje fordi de beskriver den gamle prosessens miljøtilstand, ikke historiske finansielle fakta.

Detaljert bruk og cutover-runbook: [`docs/d1-bootstrap.md`](d1-bootstrap.md).

## Lokal Wrangler/D1-validering

CI bruker en egen konto-uavhengig konfigurasjon:

```text
cloudflare/wrangler.schema-test.jsonc
```

Schema og referansedata valideres lokalt med:

```bash
npx --yes wrangler@4 d1 migrations apply DB \
  --local \
  --config cloudflare/wrangler.schema-test.jsonc
```

Phase 15.2 bygger deretter en deterministisk referansesnapshot, eksporterer bootstrap-pakken, importerer den gjennom Wranglers faktiske lokale D1-runtime og krever eksakt manifest-/nøkkeltallsparitet.

Manuell integrity check kan kjøres med:

```bash
npx --yes wrangler@4 d1 execute DB \
  --local \
  --config cloudflare/wrangler.schema-test.jsonc \
  --command "PRAGMA foreign_key_check;"
```

## Opprettelse av faktisk produksjons-D1

Dette gjøres først når Cloudflare-kontoressursene skal opprettes:

```bash
npx wrangler d1 create otello-nav --location=weur
```

Den returnerte database-ID-en legges i den endelige Wrangler-konfigurasjonen, ikke i eksempelkonfigurasjonen.

Deretter anvendes migrations mot remote D1 og den konkrete validerte produksjons-bootstrapen importeres. Remote import er ikke gjennomført i Phase 15.2 fordi den faktiske D1-ressursen ennå ikke er opprettet.

## Endringskontroll

Phase 15.1–15.2 endrer ikke:

- NAV-formelen;
- cash-modellen;
- ONA-logikken;
- buyback-estimatoren;
- Safe Harbour-backtesten;
- markedsdatakildenes finansielle prioritet.

D1-adapteren i neste fase må produsere samme API-output før Cloudflare-versjonen får overta som produksjonsmaster.
