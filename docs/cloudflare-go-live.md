# Phase 15.7 – Cloudflare go-live

Denne runbooken gjør den CI-validerte Cloudflare-implementasjonen om til det faktiske produksjonssystemet. Repository-koden kan ferdigstilles uten kontotilgang; opprettelse av ressurser, secrets og første remote deploy krever tilgang til riktig Cloudflare-konto.

Sist kontrollert mot Cloudflare-dokumentasjonen: **18.08.2026**.

## 1. Plan og ressursgrenser

Bruk **Workers Paid** i produksjon.

Applikasjonen inneholder Python Workflows som blant annet parser NewsWeb-PDF-er, gjør full refresh og skriver et deterministisk logisk D1-snapshot til R2. Workers Free har 10 ms CPU per invokasjon og er ikke et realistisk produksjonsmiljø for disse stegene.

Produksjonskonfigurasjonen renderer derfor følgende guardrails:

```json
{
  "limits": {
    "cpu_ms": 60000,
    "subrequests": 2000
  }
}
```

Dette er maksimumsgrenser, ikke mål. Workers Paid kan per 18.08.2026 konfigureres opp til 5 minutter CPU per ordinær Worker-invokasjon, mens minnegrensen fortsatt er 128 MiB. Workflows deler Worker-CPU-grensene og kan også konfigureres opp til 5 minutter aktiv CPU per steg. Etter go-live skal faktisk CPU-/minnebruk vurderes i Workers Logs.

## 2. Opprett kontoressurser

Fra `cloudflare/` etter autentisering av Wrangler:

```bash
npx wrangler d1 create otello-nav --location=weur
npx wrangler r2 bucket create otello-source-archive
```

`weur` er fortsatt en gyldig D1 location hint. Dersom det er et eksplisitt krav at D1-data bare skal ligge i EU, kan databasen i stedet opprettes med `--jurisdiction=eu`. Jurisdiction kan ikke legges til eller endres etter at databasen er opprettet, så dette må avgjøres ved opprettelsen.

Ta vare på D1 database-ID-en som Cloudflare returnerer. Ikke commit API-token eller rendret produksjonskonfigurasjon.

## 3. Ta cutover-snapshot fra den faktiske SQLite-referansen

Bruk den konkrete løpende SQLite-databasen som inneholder den validerte Otello-historikken. **CI-fixturen skal aldri brukes som produksjonsdata.**

Kjør først den vanlige strenge preflighten:

```bash
cd backend
PYTHONPATH=. python -m app.jobs.preflight --database ../data/otello.db --strict
cd ..
```

Preflighten krever nå også:

- ingen `TEST_FIXTURE`/CI-kildedokumenter;
- siste CORE og FULL på korrekt/fersk dato;
- økonomisk NAV-overlay `ready=true` på samme dato som dashboardet;
- historiske markeds-/FX-data, rapporterte cash-ankre, NewsWeb og øvrige tidligere produksjonskrav.

Lag deretter produksjonspakken med den nye eksplisitte produksjonsmodusen:

```bash
python cloudflare/tools/d1_bootstrap.py export \
  --database data/otello.db \
  --sql data/d1-bootstrap/otello-production.sql \
  --manifest data/d1-bootstrap/otello-production.manifest.json \
  --production \
  --date YYYY-MM-DD
```

`--production` kjører streng preflight **før** SQL/manifest skrives. Hvis databasen inneholder CI-fixture, økonomisk NAV ikke er klart, eller andre produksjonskrav feiler, opprettes ingen cutover-pakke.

Den reelle databasebanen kan være en annen. Bruk alltid den faktiske validerte referansefilen.

## 4. Render produksjonskonfigurasjon

Sett miljøverdier lokalt:

```text
CLOUDFLARE_D1_DATABASE_ID=<faktisk D1 UUID>
CLOUDFLARE_WORKER_NAME=otello-tracker
CLOUDFLARE_D1_DATABASE_NAME=otello-nav
CLOUDFLARE_R2_BUCKET_NAME=otello-source-archive
CLOUDFLARE_CUSTOM_DOMAIN=<valgfritt hostname>
```

Render:

```bash
python cloudflare/tools/render_production_config.py
```

Generert `cloudflare/wrangler.production.jsonc` er gitignored. Den aktiverer Workers Logs, bruker reelle D1/R2-bindings og setter Custom Domain bare når hostname er oppgitt. Uten custom domain kan første deploy bruke `workers.dev`.

## 5. Legg schema og historikk i remote D1

```bash
cd cloudflare
npx wrangler d1 migrations apply DB --remote --config wrangler.production.jsonc
npx wrangler d1 execute DB --remote --config wrangler.production.jsonc \
  --file ../data/d1-bootstrap/otello-production.sql
```

Dette skal gjøres **før** automatisk produksjonsdeploy aktiveres.

Etter import bør minst følgende kontrolleres remote:

```bash
npx wrangler d1 execute DB --remote --config wrangler.production.jsonc \
  --command "PRAGMA foreign_key_check;"
```

Bootstrap-SQL og manifest holdes utenfor Git.

## 6. GitHub production environment

Opprett GitHub environment `production` og legg inn disse **secrets**:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_D1_DATABASE_ID
```

Bruk et avgrenset API-token for riktig Cloudflare-konto/zone; ikke Global API Key.

Deployment-pathen trenger minst nødvendige rettigheter for Worker, D1 og R2, og route/domain-rettighet bare hvis Custom Domain brukes.

Legg inn disse **variables**:

```text
CLOUDFLARE_WORKER_NAME=otello-tracker
CLOUDFLARE_D1_DATABASE_NAME=otello-nav
CLOUDFLARE_R2_BUCKET_NAME=otello-source-archive
CLOUDFLARE_CUSTOM_DOMAIN=             # valgfritt ved første deploy
CLOUDFLARE_PUBLIC_URL=https://...     # brukes til HTTP-akseptanse
CLOUDFLARE_DEPLOY_ENABLED=false
```

`.github/workflows/deploy-cloudflare.yml` kan kjøres manuelt. Push til `main` deployer bare når `CLOUDFLARE_DEPLOY_ENABLED=true`.

Workflowen stopper nå tidlig dersom Worker-navn, D1-navn, R2-navn eller nødvendige credentials mangler.

## 7. Første deploy

Kjør **Deploy Cloudflare production** manuelt i GitHub Actions.

Workflowen:

1. bygger frontend;
2. renderer produksjonskonfigurasjon;
3. legger remote D1-migreringer;
4. deployer Python Worker + Workflow med `pywrangler`;
5. kaller `/api/health`, `/api/dashboard/summary` og `/api/dashboard/economic` når `CLOUDFLARE_PUBLIC_URL` er satt;
6. krever at summary og økonomisk NAV er `ready=true` og på samme dato;
7. krever at økonomisk NAV ikke overstiger regnskapsmessig FULL NAV i den konservative overlay-modellen;
8. feiler hvis modelldatoen er mer enn syv kalenderdager gammel.

Hvis `CLOUDFLARE_PUBLIC_URL` mangler, fullføres deployen med en eksplisitt warning om at HTTP-akseptansen ble hoppet over. **Ikke sett `CLOUDFLARE_DEPLOY_ENABLED=true` før en deploy med faktisk HTTP-akseptanse har passert.**

## 8. Custom Domain / HTTPS

Worker er applikasjonens origin, så Cloudflare Custom Domain er ønsket endelig routing. Sett for eksempel:

```text
CLOUDFLARE_CUSTOM_DOMAIN=otello.example.com
CLOUDFLARE_PUBLIC_URL=https://otello.example.com
```

Hostnavnet må ligge i en Cloudflare-håndtert zone og må ikke kollidere med eksisterende DNS-oppsett. Cloudflare håndterer sertifikat/HTTPS for Worker Custom Domain.

## 9. Observability og faktisk ressursbruk

Produksjonskonfigurasjonen aktiverer Workers Logs med høy sampling under første go-live. Etter flere normale 30-minutters refresher og minst én full Workflow-kjøring, kontroller:

- invocation outcome/errors;
- CPU time og wall time;
- `exceededCpu`/minnefeil;
- Workflow step failures/retries;
- `job_runs` og `source_health` i D1;
- R2-objekter for råkilder, PDF-er og snapshots.

128 MiB isolate-minne gjelder fortsatt, så de eksisterende bounded/streaming-reglene for store payloads skal beholdes.

## 10. D1 Time Travel restore drill

Cloudflare D1 Time Travel er alltid aktivert på produksjonsbackend. Per 18.08.2026 kan Workers Paid gjenopprette til et tidspunkt innenfor de siste 30 dagene; Free har kortere historikk.

Time Travel restore overskriver databasen på stedet og er destruktiv. Ikke test tilfeldig restore mot live produksjonsdatabase.

Før go-live, bruk en egen drill-database eller et kontrollert vedlikeholdsvindu:

```bash
npx wrangler d1 time-travel info <database>
npx wrangler d1 time-travel info <database> --timestamp="<RFC3339>"
npx wrangler d1 time-travel restore <database> --bookmark="<bookmark>"
```

Prosedyre:

1. noter current bookmark;
2. gjør en harmløs kjent mutasjon i drill-databasen;
3. restore til tidligere bookmark/timestamp;
4. verifiser at mutasjonen forsvinner;
5. noter bookmark som gjør det mulig å angre restore.

Phase 15.6 R2-logisk snapshot er et separat audit/repro-arkiv og erstatter ikke Time Travel.

## 11. Endelig produksjonsakseptanse

Go-live er ferdig først når alle punktene under er sanne:

- remote D1 inneholder den validerte **produksjons**-cutover-historikken;
- ingen CI/test-fixture finnes i produksjonsdatabasen;
- remote D1 migrations er current;
- Worker deploy fra GitHub er grønn;
- `/api/health` er healthy;
- dashboard summary er `ready` og fersk;
- økonomisk NAV er `ready`, samme dato som summary og vises i dashboardet;
- en 30-minutters scheduled refresh fullfører uten uventet `PARTIAL`/`FAILED`;
- én daglig full Workflow fullfører;
- Workers Logs viser ingen CPU-/minnegrensefeil;
- forventede råfiler/PDF/snapshot finnes i R2;
- Custom Domain HTTPS fungerer dersom aktivert;
- D1 restore drill er gjennomført trygt;
- først deretter settes `CLOUDFLARE_DEPLOY_ENABLED=true`.

## 12. Det som fortsatt må finnes før første remote cutover

Repository-siden er laget slik at den kan ferdigstilles uten konto- eller produksjonsdata. Før faktisk remote cutover trengs derfor fortsatt:

1. reell validert SQLite-referansedatabase (`otello.db` eller tilsvarende);
2. faktisk Cloudflare D1-ressurs og database-ID;
3. faktisk R2-bucket;
4. GitHub production secrets/variables;
5. valgt første offentlig URL (`workers.dev` eller Custom Domain).

Ikke erstatt punkt 1 med `build_d1_bootstrap_fixture.py` eller andre CI-data.
