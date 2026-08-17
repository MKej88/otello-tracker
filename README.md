# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med løpende NAV, historisk NAV-rabatt, tilbakekjøp, Bemobi-eksponering og eksplisitt datakvalitet.

## Status 17.08.2026

Kjernemodellen og live-feedene finnes i den validerte SQLite-referanseimplementasjonen. Produksjonsmålet er **Cloudflare-native**.

Cloudflare-migreringen har nå kommet gjennom read-only dashboardet:

- **15.1:** D1-schema og structural parity – ferdig
- **15.2:** deterministisk SQLite → D1 bootstrap/data parity – ferdig lokalt
- **15.3:** Python Worker + FastAPI + D1 read API + React Static Assets – ferdig lokalt
- **15.3.1:** Cloudflare hardening, query-budget og populated-D1 HTTP parity – ferdig og CI-validert
- **15.4:** scheduled ingestion – neste fase

Se [PHASE.md](PHASE.md), [docs/cloud-deployment.md](docs/cloud-deployment.md), [docs/d1-migration.md](docs/d1-migration.md), [docs/d1-bootstrap.md](docs/d1-bootstrap.md), [docs/worker-api.md](docs/worker-api.md) og [docs/production-readiness.md](docs/production-readiness.md).

## Produksjonsarkitektur – Cloudflare

```text
Browser
  |
  v
Cloudflare Python Worker + Static Assets
  |-- FastAPI /api/*
  |-- React/Vite
  |
  +--> D1             strukturert produksjonsdata
  +--> R2             PDF/råkilder/arkiv
  +--> Cron Triggers  fast refresh
  +--> Workflows      tyngre fullrefresh/retries
  +--> Secrets        API-nøkler
```

Docker Compose/Nginx/SQLite beholdes som lokal regresjonsreferanse under migreringen, men er ikke produksjonsmålet.

## Implementert Worker API

```text
GET /api/health
GET /api/dashboard/summary
GET /api/dashboard/history
GET /api/buybacks/forecast
```

`/api/health` gjør en faktisk D1-readiness-query. Dashboardets tre datakontrakter er differensielt parity-testet mot referansebackenden.

React/Vite serveres som Workers Static Assets på samme origin. `/api/*` kjøres Worker-first og frontend-ruter har SPA-fallback.

## Phase 15.3.1 hardening

Hardening-fasen før write-paths/scheduling gjør følgende uten å endre finansielle modeller:

- buyback-prognosen leser OTEC-aktivitet én gang per kall i stedet for to D1-spørringer per historisk programuke;
- full ready-path er beskyttet av en eksplisitt D1 query-budget-test;
- bounded activity-vinduet beholder de nyeste radene og returnerer dem kronologisk til den uendrede modellen;
- D1 får egne read-performance-indekser for buyback-program og NAV-serie;
- CI bygger et populated referansedatasett, eksporterer det til ekte lokal Wrangler D1, starter faktisk `workerd` og krever eksakt HTTP-JSON-paritet mot SQLite-referansen;
- statiske assets får CSP og øvrige sikkerhetsheadere via `frontend/public/_headers`;
- Worker-genererte API-responser får egne sikkerhets- og cache-headere;
- fingerprintede Vite-assets kan cache aggressivt, mens dynamiske API-kontrakter har korte/bundne cachevinduer.

## D1

D1 er planlagt som autoritativ produksjonsdatabase for market data, FX, holdings, cash, ONA, corporate actions, buybacks, CORE/FULL NAV, NewsWeb/CVM metadata og jobbstatus.

D1-migreringene ligger i:

```text
cloudflare/migrations/
  0001_initial_schema.sql
  0002_reference_data.sql
  0003_query_indexes.sql
```

`0001_initial_schema.sql` genereres deterministisk fra den migrerte SQLite-referansen. `0003` inneholder Cloudflare/D1-spesifikke ytelsesindekser som ikke endrer datamodellens finansielle semantikk.

## Historisk bootstrap

Phase 15.2 kan eksportere en validert SQLite-snapshot til portabel D1-SQL med radtall, SHA-256 per tabell, global logisk hash og kontrollverdier for NAV, market/FX, cash, ONA, share count, holdings og buybacks. Den konkrete produksjonssnapshoten tas først ved cutover til faktisk remote `otello-nav`.

## NAV-definisjoner

`CORE NAV`:

```text
Bemobi markedsverdi + modellert/rapportert cash
```

`FULL NAV`:

```text
CORE NAV + øvrige nettoeiendeler/-forpliktelser (ONA)
```

Rapportert ONA:

```text
Total assets - cash - Bemobi carrying value - total liabilities
```

Mellom rapporter merkes estimerte/forecast-komponenter eksplisitt. `ALIGNED`, `MIXED`, `STALE` og `UNKNOWN` beskriver dato-/ferskhetsstatus på markedsinputene.

## Datakilder

- **B3:** BMOB3 delayed + daglig COTAHIST
- **ECB:** BRL/NOK og USD/NOK
- **Euronext:** OTEC delayed/historikk
- **NewsWeb:** Otello-meldinger og buybacks
- **CVM:** Bemobi selskapsmeldinger
- **Otello-rapporter:** kuraterte finansielle ankere
- **MFN:** sekundær fallback/discovery
- **Investing.com CSV:** kun manuell historisk OTEC-fallback

## R2

R2 skal brukes til større/binære kildeobjekter som NewsWeb-PDF-er, rå CSV/ZIP-kilder, historiske importfiler og eksport/snapshots. R2 brukes ikke som SQLite-filsystem.

## Neste fase – 15.4

Scheduled ingestion skal portere write-paths eksplisitt til Worker/D1 i stedet for å kopiere dagens synkrone SQLite-jobb:

```text
Cron Trigger
    |
    +--> OTEC delayed/EOD
    +--> BMOB3 delayed/EOD
    +--> NewsWeb incremental
    |
    v
D1 writes
    |
    v
dirty-state cash/NAV
```

Store payloads og tyngre jobber skal behandles innenfor Worker-limits og ved behov flyttes til Workflow/R2 i stedet for å lastes ukritisk inn i Worker-minnet.

## Lokal validering

Backend:

```bash
cd backend
pip install -r requirements-dev.txt
python -m pip check
PYTHONPATH=. pytest -q
```

D1:

```bash
python cloudflare/tools/generate_d1_schema.py --check
npx --yes wrangler@4 d1 migrations apply DB --local --config cloudflare/wrangler.schema-test.jsonc
```

Frontend:

```bash
cd frontend
npm ci
npm audit --omit=dev --audit-level=high
npm run build
```

Worker:

```bash
cd cloudflare
python -m pip install workers-py==1.16.4 uv==0.12.3
npm install --no-save wrangler@4.123.0
pywrangler deploy --dry-run --config wrangler.worker-test.jsonc
pywrangler dev --config wrangler.worker-test.jsonc
```

## Produksjonsporter som gjenstår

Før Cloudflare-go-live skal:

1. den konkrete SQLite-cutover-snapshoten importeres og valideres mot remote D1;
2. scheduled ingestion kjøre i Cron;
3. full refresh/retries flyttes til Workflows;
4. R2 source archive være på plass;
5. D1 preflight/data-health passere;
6. reell Worker CPU/memory/D1-bruk måles;
7. GitHub → Cloudflare deploy være grønn;
8. custom domain/HTTPS og observability fungere;
9. D1 recovery/Time Travel testes;
10. siste rapporterte Otello-ankre avstemmes før produksjon.

## Secrets

Databasefiler, API-nøkler, rå markedsdata og kilde-PDF-er skal ikke committes. Produksjonssecrets skal ligge i Cloudflare Workers Secrets/Secrets Store.
