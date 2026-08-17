# D1-migrering og schema parity

Phase 15.1 etablerer databasestrukturen for Cloudflare-produksjonen. Målet er at D1 skal ha samme strukturelle og finansielle semantikk som den validerte SQLite-referansen før API/jobber flyttes.

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

D1 håndhever foreign keys. Det genererte bootstrap-schemaet bruker derfor:

```sql
PRAGMA defer_foreign_keys = ON;
...
PRAGMA defer_foreign_keys = OFF;
```

under opprettelsen. Finansielle relasjoner, `ON DELETE`-regler og øvrige constraints beholdes.

## Parity-tester

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

Dette er strukturparitet. Finansiell **dataparitet** kommer i Phase 15.2 når historiske rader flyttes.

## Lokal Wrangler/D1-validering

CI bruker en egen konto-uavhengig konfigurasjon:

```text
cloudflare/wrangler.schema-test.jsonc
```

Den bruker en lokal D1-instans og trenger ingen ekte Cloudflare database-ID eller secret.

Schema og referansedata kan valideres lokalt med:

```bash
npx --yes wrangler@4 d1 migrations apply DB \
  --local \
  --config cloudflare/wrangler.schema-test.jsonc
```

Deretter kan integrity checks kjøres med for eksempel:

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

Deretter anvendes migrations mot remote D1 etter at lokale parity-tester er grønne.

## Historiske data – Phase 15.2

Phase 15.1 flytter **ikke** markeds-/NAV-/buybackhistorikken til en ekte D1-instans.

Phase 15.2 skal:

1. bygge en validert SQLite-referansedatabase;
2. eksportere innholdet til SQL/importformat;
3. importere radene til D1 i kontrollert rekkefølge;
4. sammenligne row counts, nøkkelrader og finansielle kontrollsummer;
5. sammenligne CORE NAV, FULL NAV og buyback-output mot referansen.

Rå SQLite-databasefil skal ikke brukes som produksjonslager i R2. R2 er kildearkiv; D1 er den strukturerte produksjonsdatabasen.

## Endringskontroll

Phase 15.1 endrer ikke:

- NAV-formelen;
- cash-modellen;
- ONA-logikken;
- buyback-estimatoren;
- Safe Harbour-backtesten;
- markedsdatakildenes finansielle prioritet.

En senere D1-adapter må produsere samme output før Cloudflare-versjonen får overta som produksjonsmaster.
