# Cloudflare go-live

Dette er runbooken for faktisk produksjonscutover. Repository-koden kan være ferdig uten Cloudflare-kontotilgang; remote ressursopprettelse og deploy gjøres separat.

## 1. Forutsetninger

Bruk **Workers Paid**. Produksjonskonfigurasjonen har bounded CPU/subrequest-grenser og bruker Workflows/R2 for de tyngre jobbene.

Ikke bruk CI-fixtures som produksjonsdata. Ikke legg API-token i Git eller chat.

**Kostnadssikring er en del av go-live:** produksjonsdeploy krever eget domene og en aktiv WAF rate-limit-regel for `/api/*`. Se `docs/cloudflare-paid-cost-guard.md`.

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
CLOUDFLARE_CUSTOM_DOMAIN=<produksjonshostname>
```

Render:

```bash
python cloudflare/tools/render_production_config.py
```

`cloudflare/wrangler.production.jsonc` er generert og gitignored. Uten custom domain kan config fortsatt renderes lokalt for dry-run, men GitHub-produksjonsdeploy nekter å fortsette.

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
CLOUDFLARE_CUSTOM_DOMAIN=nav.dittdomene.no
CLOUDFLARE_PUBLIC_URL=https://nav.dittdomene.no
CLOUDFLARE_WAF_COST_GUARD_READY=true
CLOUDFLARE_DEPLOY_ENABLED=false
```

Sett **ikke** `CLOUDFLARE_WAF_COST_GUARD_READY=true` før WAF rate limiting for `/api/*` faktisk er aktiv på domenet. Hold automatisk deploy deaktivert under første cutover.

## 9. WAF og budsjettvarsler før første deploy

Følg `docs/cloudflare-paid-cost-guard.md`:

1. opprett rate limiting-regel for `/api/*` tilpasset domenets WAF-plan;
2. opprett lave Budget Alerts, anbefalt USD 1 og USD 5 usage-based spend;
3. aktiver D1-varsler for Rows Read og Rows Written;
4. sett først deretter `CLOUDFLARE_WAF_COST_GUARD_READY=true` i GitHub production environment.

Budget Alerts er varsling og ikke et hardt kostnadstak. WAF-regelen er derfor den viktige sperren før Worker-invocation.

## 10. Første manuelle deploy

Kjør GitHub Action **Deploy Cloudflare production** manuelt.

Workflowen:

1. validerer custom domain og `CLOUDFLARE_WAF_COST_GUARD_READY=true`;
2. bygger dashboardet;
3. renderer produksjonskonfig;
4. applyer D1 migrations;
5. deployer Python Worker + Workflow;
6. tester `/api/health`;
7. tester `/api/dashboard/summary`;
8. tester `/api/dashboard/economic`;
9. tester `/api/dashboard/fx-backtest`;
10. tester `/api/buybacks/forecast`;
11. krever fersk modelldato og at økonomisk/konservativ NAV er konsistente;
12. krever at buyback engine ikke mangler volumhistorikk.

Dersom Worker er deployet, men en senere HTTP-akseptanse feiler, kjører workflowen `wrangler rollback` med eksplisitt rollback-melding. Uten oppgitt versjons-ID velges forrige deployerte Worker-versjon.

### Viktig om D1

Worker rollback ruller **ikke** tilbake D1 migrations. Produksjonsmigreringer skal derfor være additive/bakoverkompatible. Ved behov for database-restore brukes D1 Time Travel etter egen kontrollert prosedyre.

## 11. Scheduling / writer-lock

Produksjon:

```text
Fast Cron:      */30 * * * *
Full Workflow:  35 3 * * *
```

Begge bruker D1 advisory writer-lock. Kontroller i `job_runs`/Workers Logs at fast refresh hopper over kontrollert dersom full Workflow fortsatt holder låsen.

Fast Cron kjører hvert 30. minutt og er derfor underlagt Cloudflares 30-sekunders CPU-grense for Cron-intervaller under én time, uavhengig av at Workerens generelle Paid-grense er satt høyere. Full Workflow har større compute-headroom for de tunge jobbene.

## 12. Observability

Produksjon lagrer 5 % av Workers invocation logs og har tracing avslått som standard. Ved feilsøking kan real-time tailing brukes uten å la høy sampling stå permanent.

Etter flere normale fast-kjøringer og minst én full Workflow, kontroller:

- invocation outcome/errors;
- CPU/wall time;
- minnefeil/CPU-limit;
- Workflow step retries/failures;
- `job_runs` og `source_health`;
- writer-lock ikke blir hengende etter normal fullføring;
- R2 råkilder/PDF-er/snapshot;
- økonomisk NAV/cash-FX-quality;
- buyback forecast status;
- Workers/D1/R2/Workflow billable usage.

## 13. R2 auditsnapshot

D1 Time Travel på Workers Paid er primær korttids-gjenoppretting. Det separate logiske R2-snapshotet tas derfor **ukentlig (søndag) og ved månedsslutt**, ikke daglig.

Snapshotet skal inneholde finans-/modellstate, inkludert:

- cash/ONA/NAV;
- holdings/share counts;
- corporate actions/buybacks;
- broker estimate sets/values;
- consensus snapshots;
- provenance.

`company_news`, `market_activity` og `runtime_state` er rekonstruerbare/høyfrekvente og er ikke del av det logiske snapshotet. Full recovery ligger i D1 Time Travel.

## 14. D1 Time Travel drill

Gjør restore-test mot egen drill-database eller kontrollert vedlikeholdsvindu – ikke tilfeldig mot live D1.

Prosedyre:

1. noter current bookmark;
2. gjør en harmløs kjent mutasjon i drill-databasen;
3. restore til tidligere bookmark/tidspunkt;
4. verifiser at mutasjonen forsvinner;
5. dokumenter hvordan restore eventuelt reverseres.

## 15. Custom domain

Custom domain er nå et krav for produksjonsworkflowen slik at WAF kan stoppe misbruk før `/api/*` når Worker-koden. Cloudflare håndterer HTTPS for Worker Custom Domain.

## 16. Endelig akseptanse

Go-live er godkjent først når:

- [ ] production bootstrap-preflight passerte;
- [ ] remote D1 importerte riktig produksjonshistorikk;
- [ ] `verify-remote` ga eksakt manifestparitet;
- [ ] ingen testfixtures finnes remote;
- [ ] custom domain er satt;
- [ ] WAF rate limiting for `/api/*` er aktiv;
- [ ] Budget Alerts er opprettet;
- [ ] D1 billing notifications er aktivert;
- [ ] `CLOUDFLARE_WAF_COST_GUARD_READY=true` er satt;
- [ ] Worker-deploy er grønn;
- [ ] summary/economic/FX-backtest/buyback HTTP-akseptanse er grønn;
- [ ] minst én fast refresh er kontrollert;
- [ ] minst én full Workflow er kontrollert;
- [ ] writer-lock fungerer som forventet;
- [ ] R2 råfiler/PDF/snapshot finnes etter retention-policy;
- [ ] Workers Logs viser akseptabel CPU/minnebruk;
- [ ] Time Travel restore-drill er gjennomført.

Først etter dette settes:

```text
CLOUDFLARE_DEPLOY_ENABLED=true
```

## 17. Neste rapportanker

Ved Otello 1H26 skal nye rapporterte cash-/balanse-/ONA-/opsjonsdata avstemmes. Driftskostnadsankrene oppdateres til ny rapport dersom bedre run-rate-data finnes. Cash-valutafordeling legges kun inn dersom rapporten faktisk dokumenterer den; ellers gjettes den ikke.
