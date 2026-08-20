# D1 eksport og verifisering

`cloudflare/tools/d1_bootstrap.py` er et deterministisk verktøy for å eksportere og kontrollere en validert SQLite-referanse mot D1. Det ble opprinnelig brukt ved første cutover, men beholdes nå for **referanse, recovery og kontroll**.

Det finnes ikke lenger en generell GitHub-workflow som automatisk importerer et historisk bootstrapsett til produksjons-D1.

## Kommandoer

```text
export          SQLite -> deterministisk SQL + manifest
verify          lokal D1/SQLite mot manifest
verify-remote   remote D1 read-only export -> eksakt manifestparitet
```

## Manifest

Manifestet brukes til å kontrollere blant annet:

- kolonneorden;
- radtall;
- logisk SHA-256 per tabell;
- global logisk SHA-256;
- sentrale finansielle kontrollpunkter.

Hashene er logiske og skal ikke avhenge av SQLite page-layout, WAL eller andre fysiske filattributter.

`bemobi_investor_facts` inngår nå i manifestet som referansedata sammen med `sources` og `instruments`. Tabellen seeder kildebelagte Bemobi-resultater, eierandel, verdsettelsesankre og konsensusfakta gjennom SQLite `0019` / D1 `0009`. Bootstrapen re-inserter ikke disse referanseradene; den kontrollerer at de er identiske og synkroniserer kun migreringsgenererte tidsstempler for eksakt logisk paritet.

## Lokal eksport

Eksempel fra repo-roten:

```bash
python cloudflare/tools/d1_bootstrap.py export \
  --database data/otello_nav.db \
  --sql data/d1-bootstrap/bootstrap.sql \
  --manifest data/d1-bootstrap/manifest.json
```

Genererte bootstrapfiler skal ikke committes. De kan inneholde komplette historiske data og ligger derfor utenfor Git.

## Lokal D1-verifisering

CI bruker verktøyet til å bygge en deterministisk referansefixture, importere den i lokal Wrangler D1 og verifisere eksakt logisk paritet. Kildedatabasen må stå på siste aktive SQLite-migrering, som per 20.08.2026 er `0019`.

Manuell kontroll kan gjøres med:

```bash
python cloudflare/tools/d1_bootstrap.py verify \
  --database cloudflare/.wrangler/state/v3/d1 \
  --manifest data/d1-bootstrap/manifest.json
```

## Remote verifisering

`verify-remote` skal brukes som **read-only kontroll** når en kjent manifestreferanse skal sammenlignes med D1.

Ikke bruk det gamle cutover-mønsteret som en rutinemessig måte å overskrive produksjonsdatabasen på. Produksjons-D1 er nå autoritativ og normal videreutvikling skjer gjennom additive migreringer og ordinære write-paths.

Ved alvorlig databasefeil er D1 Time Travel primær recovery-mekanisme. Se `docs/runbook.md`.

## Avgrensning

Verktøyet endrer ikke NAV-formler, cash-metodikk, ONA, buyback-estimator eller kildeprioritet. Det serialiserer og kontrollerer eksisterende data.

For migreringsregler og reserverte numre, se `docs/migration-history.md`.
