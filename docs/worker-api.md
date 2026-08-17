# Cloudflare Worker API og D1 repository

Phase 15.3 flytter det lesende dashboard-API-et fra FastAPI/SQLite-referansen til en Cloudflare Python Worker med D1, uten å endre finansielle beregningsregler. Phase 15.3.1 hardener denne read-pathen før scheduled ingestion introduserer writes.

## Arkitektur

```text
React/Vite static assets
        |
        | samme Worker / origin
        v
Cloudflare Worker + FastAPI
        |
        v
read-only D1Repository
        |
        v
D1
```

`/api/*` sendes gjennom Worker-koden. Vanlige frontend-filer serveres som Workers Static Assets, og ukjente frontend-ruter får SPA-fallback til `index.html`.

## API-kontrakter

Worker-rutene er:

- `GET /api/health`
- `GET /api/dashboard/summary`
- `GET /api/dashboard/history?days=...&max_points=...`
- `GET /api/buybacks/forecast?as_of_date=YYYY-MM-DD`

`/api/health` gjør en faktisk `SELECT 1` mot D1 og er dermed en readiness-kontroll.

## Read-only D1 repository

`cloudflare/src/repository.py` har kun lesehjelpere `all(sql, parameters)` og `first(sql, parameters)`. SQL kjøres med D1 `prepare()` og `bind()`. Write-paths introduseres separat i Phase 15.4/15.5.

## Exact parity mot referansebackend

`backend/tests/test_cloudflare_worker_parity.py` krever eksakt lik JSON-output for dashboard summary, dashboard history, buyback forecast og Oslo Børs-handelskalender. Buyback-testen beskytter fortsatt methodology version `otec-buyback-safe-harbour-program-v1` og det etablerte punktestimatnivået.

## Phase 15.3.1 – D1 query-budget

Den første Worker-porten gjorde to `market_activity`-queries for hver historiske programuke i buyback-prognosen. 15.3.1 laster i stedet et bounded, kronologisk OTEC activity-sett én gang per ready forecast og gjenbruker det til kommende ADV20, historiske lookbacks og aktivitet i programukene.

Full ready-path bruker nå tre repository-queries:

1. aktivt program/siste periode;
2. bounded OTEC market activity;
3. programuker.

`backend/tests/test_cloudflare_worker_hardening.py` feiler hvis query-budgetet driver opp. Safe Harbour-reglene og alle matematiske beregninger er uendret.

## D1 read-indekser

`cloudflare/migrations/0003_query_indexes.sql` legger til Cloudflare-spesifikke ytelsesindekser:

```text
buybacks(program_id, trade_date, id)
nav_snapshots(calculation_version, nav_scope, as_of_at)
```

De endrer ikke constraints, data eller finansiell semantikk.

## Populated D1 → workerd → HTTP parity

15.3 smoke-testet først Worker-runtime mot en tom D1. 15.3.1 lukker gapet:

1. bygg en deterministisk populated SQLite-referanse;
2. beregn forventet summary/history/forecast med referansebackenden;
3. eksporter samme snapshot gjennom Phase 15.2 bootstrap-pipeline;
4. importer den til faktisk lokal Wrangler D1;
5. verifiser logical hash/FK parity;
6. bygg og start faktisk Python `workerd`;
7. kall API-rutene over HTTP;
8. krev eksakt JSON-likhet med referansepayloadene.

Dermed testes D1-binding, SQL, Pyodide/Python-importer, FastAPI/ASGI, routing og serialisering i én kjede med populated data.

## Security headers

Statiske Worker-assets får headers fra `frontend/public/_headers`, som Vite kopierer til `frontend/dist/_headers`: CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy og Permissions-Policy.

Worker-genererte API-responser får tilsvarende browser-hardening direkte fra FastAPI-middleware. `_headers` brukes ikke som en erstatning for headers på dynamisk Worker-output.

## Cache-policy

```text
/api/health                no-store
/api/dashboard/summary     max-age=30
/api/dashboard/history     max-age=900
/api/buybacks/forecast     max-age=900
/assets/*                  max-age=31536000, immutable
```

Dette reduserer unødvendige Worker/D1-kall uten å gjøre summary-data vesentlig tregere.

## Worker-runtime i CI

CI bruker pinnet Worker-verktøykjede:

```text
workers-py==1.16.4
workers-runtime-sdk==1.6.13
uv==0.12.3
wrangler==4.123.0
```

CI bygger React/Vite, anvender alle D1 migrations, verifiserer performance-indeksene, bygger Worker med `pywrangler deploy --dry-run`, starter `pywrangler dev`, kontrollerer static assets/SPA og validerer security/cache headers.

## Lokal kjøring

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

## Remote deploy

Read-pathen er fortsatt ikke produksjonsmaster. Før remote deploy skal vi opprette faktisk `otello-nav` D1, ta konkret cutover-snapshot, importere/verifisere remote D1, fullføre Worker-native scheduled ingestion og måle CPU/memory/D1-bruk på ekte Cloudflare.

## Endringskontroll

Phase 15.3/15.3.1 endrer ikke NAV-formelen, cash-/ONA-metodikken, buyback-estimatoren, Safe Harbour-logikken, markedsdatakildenes finansielle prioritet eller historiske data.
