# D1-migrering og schema-paritet

D1 er autoritativ produksjonsdatabase. SQLite-backenden beholdes som deterministisk referanseimplementasjon, og CI kontrollerer at Cloudflare/D1 fortsatt har samme strukturelle og finansielle semantikk.

## Schema-paritet

`cloudflare/tools/generate_d1_schema.py` bygger et konsolidert D1-basisschema fra backendens migrerte SQLite-schema. CI kjører generatoren med `--check` og feiler ved schema-drift.

Det betyr at endringer i databasestrukturen skal gjøres kontrollert og testes mot både SQLite-referansen og lokal Wrangler D1.

## D1-migreringer

Produksjonsmigreringer ligger i:

```text
cloudflare/migrations/
```

Regler:

1. eksisterende migreringer som kan være kjørt i en database skal ikke omskrives;
2. nye migreringer skal være additive og bakoverkompatible;
3. migreringsnumre som har vært brukt skal aldri gjenbrukes;
4. Worker-rollback ruller ikke tilbake D1-migreringer;
5. D1 Time Travel er recovery-mekanismen ved behov for full database-restore.

Se `docs/migration-history.md` for reserverte numre. Etter at aksjonær-/Top 20-funksjonen ble fjernet er Cloudflare `0008` og SQLite `0018` historisk brukt/reservert. Neste nye migrering skal derfor minst være Cloudflare `0009_...` og SQLite `0019_...`.

## Lokal validering

CI bruker lokal Wrangler D1 til å:

- anvende migreringer;
- bygge/importere deterministisk referansefixture;
- kontrollere foreign keys;
- kontrollere schema/data-paritet;
- kjøre Worker HTTP-paritet mot faktisk lokal D1-runtime.

Eksempel på lokal migrering:

```bash
npx --yes wrangler@4.123.0 d1 migrations apply DB \
  --local \
  --config cloudflare/wrangler.schema-test.jsonc
```

Eksempel på foreign-key-kontroll:

```bash
npx --yes wrangler@4.123.0 d1 execute DB \
  --local \
  --config cloudflare/wrangler.schema-test.jsonc \
  --command "PRAGMA foreign_key_check;"
```

## Produksjon

Produksjonsdeployen kjører remote D1-migreringer før Worker deployes og etterfølges av HTTP-akseptanse.

Fordi en Worker-rollback ikke reverserer schemaendringer, må migreringen være kompatibel med både gammel og ny Worker i overgangsøyeblikket. Breaking schema-endringer skal derfor splittes i flere additive steg.

## Data-paritet og recoveryverktøy

`cloudflare/tools/d1_bootstrap.py` beholdes for deterministisk eksport/verifisering av referansedata, men er ikke en generell produksjonsimportknapp etter go-live.

Se:

- `docs/d1-bootstrap.md`
- `docs/runbook.md`
- `docs/migration-history.md`
