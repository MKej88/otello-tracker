# Cloudflare Worker API og D1 repository

Phase 15.3 flytter det lesende dashboard-API-et fra FastAPI/SQLite-referansen til en Cloudflare Python Worker med D1, uten å endre finansielle beregningsregler.

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

Konfigurasjonen bruker:

```json
"assets": {
  "directory": "../frontend/dist",
  "binding": "ASSETS",
  "not_found_handling": "single-page-application",
  "run_worker_first": ["/api/*"]
}
```

Dette gjør at React-dashboardet og API-et kan bruke samme origin uten CORS-lag.

## API-kontrakter i 15.3

Worker-rutene er:

- `GET /api/health`
- `GET /api/dashboard/summary`
- `GET /api/dashboard/history?days=...&max_points=...`
- `GET /api/buybacks/forecast?as_of_date=YYYY-MM-DD`

`/api/health` gjør en faktisk `SELECT 1` mot D1 og er dermed en readiness-kontroll, ikke bare en prosess-liveness.

## Read-only D1 repository

`cloudflare/src/repository.py` har kun lesehjelpere:

- `all(sql, parameters)`
- `first(sql, parameters)`

SQL kjøres med D1 `prepare()` og `bind()`. Phase 15.3 introduserer ikke ingestion- eller write-paths i Worker-API-et. Disse kommer separat i Phase 15.4/15.5.

Dette skillet er bevisst: API-porteringen skal ikke kunne endre autoritative markeds-, cash-, NAV- eller buybackdata.

## Parity mot referansebackend

`backend/tests/test_cloudflare_worker_parity.py` kjører de nye Worker-servicefunksjonene mot samme logiske datasett som SQLite-referansen og krever eksakt lik JSON-output for:

- dashboard summary, inkludert FULL/CORE-valg, endringer, freshness og Bemobi ownership presentation safeguards;
- dashboard history, inkludert bounds og downsampling;
- buyback forecast for 17.08.2026;
- Oslo Børs-handelskalender.

Buyback-testen krever fortsatt methodology version:

```text
otec-buyback-safe-harbour-program-v1
```

og beskytter samtidig det etablerte punktestimatnivået rundt 62k aksjer. Dette er en regresjonsvakt, ikke en ny modell.

## Lokal Worker-runtime i CI

CI bruker pinning for selve Worker-verktøykjeden:

```text
workers-py==1.16.4
workers-runtime-sdk==1.6.13
uv==0.12.3
wrangler==4.123.0
```

CI gjør deretter:

1. bygger React/Vite til `frontend/dist`;
2. kjører D1-migreringene lokalt;
3. bygger Python Worker med `pywrangler deploy --dry-run`;
4. starter faktisk lokal `workerd` via `pywrangler dev`;
5. kaller health, summary, history og forecast over HTTP;
6. verifiserer at `/` serverer React-indexen;
7. verifiserer SPA-fallback på en vilkårlig frontend-rute.

Dermed tester vi både Python-import/runtime, D1-binding, FastAPI/ASGI, API-routing og Workers Static Assets i samme kjede.

## Lokal kjøring

Fra repository root:

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

Standard `cloudflare/wrangler.jsonc` finnes fordi Pywrangler synkroniserer Python-pakker før den videresender argumenter til Wrangler og forventer en standardkonfigurasjon i prosjektmappen.

## Remote deploy

Phase 15.3 oppretter eller skriver ikke til den faktiske produksjons-D1-en. Før remote deploy skal vi fortsatt:

1. opprette faktisk `otello-nav` D1;
2. kjøre Phase 15.2-bootstrapen med det konkrete cutover-snapshotet;
3. verifisere remote data parity;
4. sette faktisk D1-ID i produksjonskonfigurasjonen;
5. først deretter deploye Worker som produksjonsmaster.

## Endringskontroll

Phase 15.3 endrer ikke:

- NAV-formelen;
- cash-/ONA-metodikken;
- buyback-estimatoren;
- Safe Harbour-logikken;
- markedsdatakildenes finansielle prioritet;
- historiske data.

Referansebackend og Docker beholdes som regresjonsgrunnlag til Cloudflare-cutover er fullført.
