# Cloudflare go-live

Dette er runbooken for faktisk produksjonscutover. Repository-koden kan være ferdig uten Cloudflare-kontotilgang; remote ressursopprettelse og deploy gjøres separat.

## 1. Forutsetninger

Bruk **Workers Paid**. Produksjonskonfigurasjonen har bounded CPU/subrequest-grenser og bruker Workflows/R2 for de tyngre jobbene.

Ikke bruk CI-fixtures som produksjonsdata. Ikke legg API-token i Git eller chat.

## 2. Opprett Cloudflare-ressurser

Fra `cloudflare/`:

```bash
npx wrangler d1 create otello-nav --location=weur
npx wrangler r2 bucket create otello-source-archive
```

Ta vare på D1 database-ID-en. Hvis EU-jurisdiction er et eksplisitt krav, avgjøres dette ved opprettelsen før data importeres.

## 3. Bygg/valider produksjonsdatabasen

En ren database kan bygges med `backend/app/jobs/bootstrap_production.py`. Bootstrapen seeder nå automatisk den kuraterte OTEC-volumhistorikken som buyback-modellen trenger.

Før cutover skal streng preflight passere:

```bash
cd backend
PYTHONPATH=. python -m app.jobs.preflight \
  --database ../data/otello.db \
  --strict
cd ..
```

Preflight blokkerer blant annet:

- CI/test-fixtures;
- manglende/fersk marked/FX;
- manglende NewsWeb/buyback-data;
- færre enn 20 positive OTEC-volumdager;
- `INSUFFICIENT_VOLUME_HISTORY` i buyback-motoren;
- manglende/forsinket CORE/FULL/ONA/cash;
- dashboard ikke ready;
- økonomisk NAV ikke ready/samme dato.

## 4. Lag deterministic cutover-pakke

```bash
python cloudflare/tools/d1_bootstrap.py export \
  --database data/otello.db \
  --sql data/d1-bootstrap/otello-production.sql \
  --manifest data/d1-bootstrap/otello-production.manifest.json \
  --production \
  --date YYYY-MM-DD
```

`--production` kjører strict preflight før filene skrives.

## 5. Render produksjonskonfigurasjon

Sett lokalt eller via GitHub production environment:

```text
CLOUDFLARE_D1_DATABASE_ID=<D1 UUID>
CLOUDFLARE_WORKER_NAME=otello-tracker
CLOUDFLARE_D1_DATABASE_NAME=otello-nav
CLOUDFLARE_R2_BUCKET_NAME=otello-source-archive
CLOUDFLARE_CUSTOM_DOMAIN=<valgfritt hostname>
```

Render:

```bash
python cloudflare/tools/render_production_config.py
```

`cloudflare/wrangler.production.jsonc` er generert og gitignored.

## 6. Migrations + bootstrap til remote D1

```bash
cd cloudflare
npx wrangler d1 migrations apply DB --remote --config wrangler.production.jsonc
npx wrangler d1 execute DB --remote --config wrangler.production.jsonc \
  --file ../data/d1-bootstrap/otello-production.sql
cd ..
```

Kontroller foreign keys:

```bash
cd cloudflare
npx wrangler d1 execute DB --remote --config wrangler.production.jsonc \
  --command "PRAGMA foreign_key_check;"
cd ..
```

## 7. Eksakt remote D1-avstemming

Foreign-key-kontroll alene er ikke tilstrekkelig. Eksporter remote D1 read-only og sammenlign alle bootstrap-tabeller, radantall, hashes og nøkkeltall med cutover-manifestet:

```bash
python cloudflare/tools/d1_bootstrap.py verify-remote \
  --database DB \
  --manifest data/d1-bootstrap/otello-production.manifest.json \
  --config cloudflare/wrangler.production.jsonc
```

Denne kontrollen må returnere `ok=true` før første Worker-deploy godkjennes.

## 8. GitHub production environment

Secrets:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_D1_DATABASE_ID
```

Variables:

```text
CLOUDFLARE_WORKER_NAME=otello-tracker
CLOUDFLARE_D1_DATABASE_NAME=otello-nav
CLOUDFLARE_R2_BUCKET_NAME=otello-source-archive
CLOUDFLARE_CUSTOM_DOMAIN=
CLOUDFLARE_PUBLIC_URL=https://...
CLOUDFLARE_DEPLOY_ENABLED=false
```

Hold automatisk deploy deaktivert under første cutover.

## 9. Første manuelle deploy

Kjør GitHub Action **Deploy Cloudflare production** manuelt.

Workflowen:

1. bygger dashboardet;
2. renderer produksjonskonfig;
3. applyer D1 migrations;
4. deployer Python Worker + Workflow;
5. tester `/api/health`;
6. tester `/api/dashboard/summary`;
7. tester `/api/dashboard/economic`;
8. tester `/api/buybacks/forecast`;
9. krever fersk modelldato og at økonomisk/konservativ NAV er konsistente;
10. krever at buyback engine ikke mangler volumhistorikk.

Dersom Worker er deployet, men en senere HTTP-akseptanse feiler, kjører workflowen `wrangler rollback` med eksplisitt rollback-melding. Uten oppgitt versjons-ID velges forrige deployerte Worker-versjon.

### Viktig om D1

Worker rollback ruller **ikke** tilbake D1 migrations. Produksjonsmigreringer skal derfor være additive/bakoverkompatible. Ved behov for database-restore brukes D1 Time Travel etter egen kontrollert prosedyre.

## 10. Scheduling / writer-lock

Produksjon:

```text
Fast Cron:      */30 * * * *
Full Workflow:  35 3 * * *
```

Begge bruker D1 advisory writer-lock. Kontroller i `job_runs`/Workers Logs at fast refresh hopper over kontrollert dersom full Workflow fortsatt holder låsen.

## 11. Observability

Etter flere normale fast-kjøringer og minst én full Workflow, kontroller:

- invocation outcome/errors;
- CPU/wall time;
- minnefeil/CPU-limit;
- Workflow step retries/failures;
- `job_runs` og `source_health`;
- writer-lock ikke blir hengende etter normal fullføring;
- R2 råkilder/PDF-er/snapshot;
- økonomisk NAV/cash-FX-quality;
- buyback forecast status.

## 12. R2 auditsnapshot

Snapshotet skal inneholde finans-/modellstate, inkludert:

- cash/ONA/NAV;
- holdings/share counts;
- corporate actions/buybacks;
- broker estimate sets/values;
- consensus snapshots;
- provenance.

`company_news`, `market_activity` og `runtime_state` er rekonstruerbare/høyfrekvente og er ikke del av det logiske snapshotet. Full recovery ligger i D1 Time Travel.

## 13. D1 Time Travel drill

Gjør restore-test mot egen drill-database eller kontrollert vedlikeholdsvindu – ikke tilfeldig mot live D1.

Prosedyre:

1. noter current bookmark;
2. gjør en harmløs kjent mutasjon i drill-databasen;
3. restore til tidligere bookmark/tidspunkt;
4. verifiser at mutasjonen forsvinner;
5. dokumenter hvordan restore eventuelt reverseres.

## 14. Custom domain

Når baseproduksjonen er godkjent kan eksempelvis:

```text
CLOUDFLARE_CUSTOM_DOMAIN=otello.example.com
CLOUDFLARE_PUBLIC_URL=https://otello.example.com
```

settes og deploy kjøres på nytt. Cloudflare håndterer HTTPS for Worker Custom Domain.

## 15. Endelig akseptanse

Go-live er godkjent først når:

- [ ] production bootstrap-preflight passerte;
- [ ] remote D1 importerte riktig produksjonshistorikk;
- [ ] `verify-remote` ga eksakt manifestparitet;
- [ ] ingen testfixtures finnes remote;
- [ ] Worker-deploy er grønn;
- [ ] summary/economic/buyback HTTP-akseptanse er grønn;
- [ ] minst én fast refresh er kontrollert;
- [ ] minst én full Workflow er kontrollert;
- [ ] writer-lock fungerer som forventet;
- [ ] R2 råfiler/PDF/snapshot finnes;
- [ ] Workers Logs viser akseptabel CPU/minnebruk;
- [ ] Time Travel restore-drill er gjennomført;
- [ ] custom domain fungerer dersom aktivert.

Først etter dette settes:

```text
CLOUDFLARE_DEPLOY_ENABLED=true
```

## 16. Neste rapportanker

Ved Otello 1H26 skal nye rapporterte cash-/balanse-/ONA-/opsjonsdata avstemmes. Driftskostnadsankrene oppdateres til ny rapport dersom bedre run-rate-data finnes. Cash-valutafordeling legges kun inn dersom rapporten faktisk dokumenterer den; ellers gjettes den ikke.
