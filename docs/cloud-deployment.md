# Cloudflare deployment

Otello-trackeren skal hostes **direkte på Cloudflare-plattformen**, ikke på en generell cloud-VM bak Cloudflare.

## Målarkitektur

```text
Browser
  |
  v
Cloudflare Worker + Static Assets
  |-- React/Vite frontend
  |-- /api/*
  |
  +--> D1              (primær database)
  +--> R2              (PDF-er, råkilder, eksport/arkiv)
  +--> Cron Triggers   (fast refresh)
  +--> Workflows       (tyngre fullrefresh/retries)
  +--> Secrets Store   (API-nøkler/secrets)
```

## Hvorfor vi ikke bruker dagens SQLite-fil direkte i Cloudflare Containers

Cloudflare Containers kan kjøre eksisterende Docker-images, men containerdisk er ephemeral. Det er derfor ikke riktig å legge den autoritative `otello.db` på containerens lokale disk.

R2 kan mounts som filsystem, men objektlagring er ikke et POSIX/SSD-filsystem og skal ikke brukes som direkte SQLite-disk for denne applikasjonen.

Produksjonsdatabasen flyttes derfor til **Cloudflare D1**. D1 er SQLite-basert SQL, men aksesseres gjennom Cloudflare bindings i Worker-runtime og ikke gjennom dagens lokale `sqlite3`-fil.

## Frontend

React/Vite beholdes. Produksjon skal serveres som **Workers Static Assets** sammen med Worker-rutene, slik at frontend og API kan bruke samme domene og deploy.

Nginx og `frontend/Dockerfile` beholdes foreløpig kun som lokal/regresjonsreferanse mens Cloudflare-migreringen pågår. De er ikke målarkitektur for produksjon.

## Backend/API

Cloudflare støtter FastAPI i Python Workers. Dette gjør Python fortsatt til et naturlig språk for API-laget.

Dagens backend kan likevel ikke deployes uendret fordi store deler av datalaget bruker synkron `sqlite3` mot en lokal fil. Migreringen må derfor skille forretningslogikk fra persistence og lage et D1-basert datalag.

Målet er å bevare:

- NAV-formler og Decimal-logikk;
- buyback-modellen;
- kildevalidering/provenance;
- dashboardets API-kontrakter;
- eksisterende regresjonstester så langt det er mulig.

## D1

D1 blir autoritativt produksjonslager for strukturerte data:

- instruments / market prices / FX;
- cash anchors og cash movements;
- holdings og corporate actions;
- NAV snapshots og historikk;
- NewsWeb/CVM metadata;
- buyback-programmer/transaksjoner;
- job status/runtime state.

Eksisterende SQL-schema skal konverteres til D1-kompatible migrations. Tabellenes finansielle semantikk skal ikke endres bare fordi lagringsmotoren endres.

## R2

R2 brukes for binære og større kildeobjekter, ikke som SQL-database:

- NewsWeb PDF-er;
- eventuelle rå CSV/ZIP-filer som skal arkiveres;
- historiske importfiler;
- eksport/snapshot som ekstra gjenopprettingslag.

D1 har egen point-in-time recovery/Time Travel. R2 brukes i tillegg for kildearkiv og eksport, ikke som erstatning for D1.

## Scheduler

Dagens langlevende scheduler-container erstattes av Cloudflare scheduling:

### Fast refresh

Cron Trigger:

```text
*/30 * * * *
```

Den skal hente lette livekilder:

- OTEC delayed LAST/EOD;
- BMOB3 delayed LAST/EOD;
- inkrementell NewsWeb/buyback;
- dirty-state cash;
- dagens CORE/FULL NAV.

### Full refresh

Tyngre jobber skal kjøres via Workflow/planlagt jobb slik at kildetrinn kan retries separat:

- ECB;
- B3 daily/history ved behov;
- CVM;
- avstemming/rebuild;
- preflight/data-health.

Cloudflare Cron kjører i UTC. Oslo-/São Paulo-markedskalendere håndteres derfor eksplisitt i applikasjonslogikken og ikke ved å anta lokal cron-tid.

## Workers-plan

Selve arkitekturen kan utvikles mot Workers Free, men produksjonsjobbene våre parser markedsdata/PDF-er og gjør mer enn en helt enkel edge-request. Free-planen har svært lav CPU-grense per Worker/Cron-invokasjon.

Produksjonsmålet settes derfor til **Workers Paid** med mindre målinger etter migreringen viser at hele jobbløpet trygt holder seg innen Free-grensene. Dette er også nødvendig dersom Cloudflare Containers senere skulle brukes for enkelte isolerte batchjobber.

## Deploy

Endelig deploy skal gå direkte fra GitHub til Cloudflare via Workers Builds eller GitHub Actions/Wrangler.

Målet er:

```text
push/merge til main
        ↓
CI + tester
        ↓
Cloudflare build/deploy
        ↓
Worker + static assets + D1 migrations
```

Deploy aktiveres først etter at D1-migreringen og API-kontraktene er verifisert.

## Migreringsrekkefølge

1. Cloudflare/Wrangler-prosjekt og statiske assets.
2. D1-schema/migrations.
3. Eksport/import fra eksisterende SQLite-testdatabase til D1.
4. D1 repository/data-access-lag.
5. Dashboard read-only API på Worker.
6. Markedsfeeds og inkrementelle write-jobber.
7. Cron Triggers/Workflows.
8. R2 kildearkiv.
9. Preflight mot D1.
10. Cloudflare deploy fra `main` og custom domain.

Docker Compose beholdes under migreringen for lokal regresjonstesting av den nåværende Python/SQLite-implementasjonen, men er ikke lenger produksjonsmålet.
