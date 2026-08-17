# Cloudflare production target

Denne katalogen er den aktive Cloudflare-native produksjonsimplementasjonen.

## Valgte tjenester

- **Python Workers + FastAPI** – dashboard-API og portert Python-forretningslogikk
- **Workers Static Assets** – React/Vite frontend
- **D1** – strukturert produksjonsdatabase
- **R2** – PDF/råkilder/arkiv i senere fase
- **Cron Triggers** – fast refresh i Phase 15.4
- **Workflows** – tyngre fullrefresh og retries i Phase 15.5
- **Workers Secrets / Secrets Store** – produksjonssecrets

Docker/SQLite beholdes kun som regresjonsreferanse og bootstrap-kilde under cutover.

## Implementert nå

```text
src/
  entry.py
  app.py
  repository.py
  dashboard_service.py
  buyback_service.py
  oslo_calendar.py

migrations/
  0001_initial_schema.sql
  0002_reference_data.sql
  0003_query_indexes.sql
```

Worker-rutene er:

```text
GET /api/health
GET /api/dashboard/summary
GET /api/dashboard/history
GET /api/buybacks/forecast
```

React/Vite ligger på samme Worker-origin. `/api/*` er Worker-first, mens øvrige paths serveres som Static Assets med SPA-fallback.

## D1

`0001_initial_schema.sql` genereres fra den fullt migrerte SQLite-referansen og skal ikke håndredigeres. `0002_reference_data.sql` oppretter stabile sources/instruments. `0003_query_indexes.sql` inneholder D1-spesifikke read-performance-indekser og endrer ikke finansielle data eller constraints.

Regenerer/verifiser basis-schema:

```bash
python cloudflare/tools/generate_d1_schema.py
python cloudflare/tools/generate_d1_schema.py --check
```

## Bootstrap og parity

`tools/d1_bootstrap.py` eksporterer en validert SQLite-snapshot til portabel D1-SQL med manifest/hashes. CI importerer denne gjennom faktisk lokal Wrangler D1 og verifierer logical parity og foreign keys.

Phase 15.3.1 går ett steg videre: en populated Worker-fixture importeres til lokal D1, faktisk `workerd` startes, og HTTP-output for summary/history/forecast må være eksakt lik referansebackenden.

## Ytelseshardening

Buyback-prognosen bruker en bounded OTEC activity-read per forecast i stedet for to D1-spørringer per historisk programuke. Ready-path har en query-budget-regresjonstest slik at D1-querybruk ikke vokser lineært med programmets alder.

D1 har egne indekser for:

```text
buybacks(program_id, trade_date, id)
nav_snapshots(calculation_version, nav_scope, as_of_at)
```

## Security/cache

Statiske assets får browser-hardening via `frontend/public/_headers`, som Vite kopierer til `dist/_headers`. Worker-genererte API-responser får sikkerhetsheadere direkte fra FastAPI-middleware.

Cache-policy:

- health: `no-store`
- summary: 30 sekunder
- history: 15 minutter
- buyback forecast: 15 minutter
- fingerprintede `/assets/*`: immutable langtids-cache

## Kontoressurser som gjenstår

Når write-paths og go-live er klare:

```bash
npx wrangler d1 create otello-nav --location=weur
npx wrangler r2 bucket create otello-source-archive
```

Deretter settes faktisk D1-ID i produksjonskonfigurasjonen og den validerte cutover-snapshoten importeres.

## Lokal Worker

Fra repo-root:

```bash
cd frontend
npm ci
npm run build
cd ../cloudflare

python -m pip install workers-py==1.16.4 uv==0.12.3
npm install --no-save wrangler@4.123.0
npx wrangler d1 migrations apply DB --local --config wrangler.worker-test.jsonc
pywrangler deploy --dry-run --config wrangler.worker-test.jsonc
pywrangler dev --config wrangler.worker-test.jsonc
```

## Neste fase

Phase 15.4 porter write-paths eksplisitt til Worker/D1:

```text
scheduled */30 * * * *
  -> OTEC delayed/EOD
  -> BMOB3 delayed/EOD
  -> NewsWeb incremental
  -> dirty-state cash/NAV
```

Dagens synkrone SQLite `fast_refresh.py` skal ikke kopieres direkte inn i Worker-runtime. Nettverkskall, payloadgrenser og D1-writes skal tilpasses Cloudflare eksplisitt.
