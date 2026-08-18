# Cloudflare production target

Denne katalogen er den aktive Cloudflare-native produksjonsimplementasjonen for Otello NAV-oversikten.

## Tjenester

- **Python Workers + FastAPI** – API og portert finans-/datakildelogikk
- **Workers Static Assets** – React/Vite-dashboard
- **D1** – strukturert produksjonsdatabase
- **R2** – råkilder, NewsWeb-PDF-er og logisk auditsnapshot
- **Cron Triggers** – bounded 30-minutters fast refresh
- **Workflows** – daglig full refresh med retries og R2-arkivering ved behov

SQLite-backenden er deterministisk regresjonsreferanse og bootstrap-kilde, ikke produksjonsdatabasen etter cutover.

## Worker API

```text
GET /api/health
GET /api/dashboard/summary
GET /api/dashboard/economic
GET /api/dashboard/fx-backtest
GET /api/dashboard/history
GET /api/buybacks/forecast
```

## Scheduling

```text
Fast refresh:   */30 * * * *
Full Workflow:  35 3 * * *   (03:35 UTC)
```

Begge write-paths bruker `runtime_state`-låsen `cloudflare_refresh_writer_lock`. Fast refresh hopper kontrollert over dersom full Workflow holder låsen. Full Workflow venter/retryer ved konflikt. Låsen har expiry slik at et krasj ikke kan blokkere systemet permanent.

## Fast refresh

Fast-banen håndterer:

- OTEC delayed/gap recovery/EOD LAST;
- BMOB3 delayed/EOD LAST;
- NewsWeb incremental;
- dirty-state cash/ONA/CORE/FULL NAV.

Den er bounded og idempotent. Euronext EOD er fortsatt `LAST / DIRECT`, ikke påstått offisiell `CLOSE`.

## Full Workflow

Daglig Workflow håndterer:

1. ECB FX;
2. B3 COTAHIST;
3. Bemobi CVM;
4. NewsWeb reconciliation;
5. NewsWeb PDF/daglige buyback-transaksjoner;
6. OTEC recovery/EOD;
7. dirty NAV;
8. D1 production-data preflight;
9. R2 logisk auditsnapshot når retention-policy krever det;
10. jobb-/source-health-finalisering.

D1-preflighten krever blant annet:

- økonomisk NAV `ready=true` og samme dato som dashboardet;
- minst 20 positive OTEC-volumdager;
- buyback engine må ikke returnere `INSUFFICIENT_VOLUME_HISTORY`;
- historisk/fersk OTEC, BMOB3, BRL/NOK og USD/NOK;
- NewsWeb-historikk og tilbakekjøpsdata.

CVM-årets komprimerte ZIP holdes bounded, og det utpakkede CSV-medlemmet leses som tekststream direkte fra ZIP. Hele CSV-en materialiseres ikke i Worker-minnet.

## Økonomisk NAV og valuta

Økonomisk NAV er separat fra CORE/FULL. Worker-pariteten leser kildebelagte kostnadsankre og cash-FX-ankre fra D1 `source_documents`.

For et cash-anker med dokumentert valutafordeling:

- USD-andel revalueres mot USD/NOK;
- BRL-andel revalueres mot BRL/NOK;
- ukjent residual holdes konservativt utenfor dokumentert revaluering i selve NAV-en.

Frontenden kan i tillegg vise residualen som estimert NOK for å illustrere sannsynlig NOK/USD/BRL-fordeling. Dette er en presentasjonsmodell og endrer ikke den konservative NAV-beregningen.

`/api/dashboard/fx-backtest` tester historisk valutaeffekt mot rapportert valutaeffekt på cash. Produksjonsakseptansen krever minst to klare historiske perioder.

## Workers Paid / ytelse

Produksjonsrenderer setter bevisst lavere grenser enn plattformens maksimum:

```text
CPU per invocation:                60 000 ms
Subrequests per invocation:        500
Workers Caching, API-entrypoint:   på
Global Workers Caching:            av
Workers Logs sampling:             5 %
Tracing:                           av
```

`assets.run_worker_first` er begrenset til `/api/*`, slik at statiske React/Vite-assets går direkte gjennom Workers Static Assets. API-et har edge-cache med endpoint-tilpassede TTL-er.

Produksjonsdeploy krever eget domene og aktiv WAF rate limiting for `/api/*`. Se `docs/cloudflare-paid-cost-guard.md`.

## R2 snapshot

Det logiske auditsnapshotet er chunked og bounded. Det inkluderer blant annet:

- `broker_estimate_sets`
- `broker_estimate_values`
- `consensus_snapshots`

Høyfrekvente/re-konstruerbare `company_news`, `market_activity` og `runtime_state` er utelatt. D1 Time Travel er full korttids-recovery.

Det logiske auditsnapshotet tas **hver søndag og ved månedsslutt**, ikke daglig. Rå kildefiler/PDF-er med provenance-verdi arkiveres fortsatt content-addressed når de hentes.

## D1 bootstrap

`tools/d1_bootstrap.py` støtter:

```text
export          SQLite → deterministisk SQL + manifest
verify          lokal D1/SQLite mot manifest
verify-remote   remote D1 read-only export → eksakt manifestparitet
```

Produksjons-`export` blokkeres dersom streng SQLite-preflight ikke er klar. Historiske OTEC-kurser må komme fra validert Euronext-CSV eller manuell Investing.com-eksport.

Etter produksjonsimport skal `verify-remote` passere før første Worker cutover godkjennes.

## Deploy

`.github/workflows/deploy-cloudflare.yml`:

1. krever Cloudflare credentials/resources, custom domain, samsvarende HTTPS public URL og aktiv WAF cost guard;
2. bygger frontend;
3. renderer produksjonskonfig;
4. applyer remote D1 migrations;
5. deployer Worker/Workflow;
6. tester den faktiske statiske frontend-siden og sikkerhetsheaders;
7. tester health, summary, history, economic NAV, FX-backtest og buyback forecast;
8. krever FX-backtest `ready=true` med minst to perioder;
9. krever fersk dashboarddato og konsistent økonomisk/konservativ NAV;
10. ruller Worker tilbake til forrige deployerte versjon dersom en senere produksjonsakseptanse feiler.

Worker rollback reverserer ikke D1 migrations. Produksjonsmigreringer skal derfor være additive/bakoverkompatible, og D1 Time Travel brukes ved database-restore.

## Produksjonsressurser

Faktiske ressurser opprettes ved go-live:

```bash
npx wrangler d1 create otello-nav --location=weur
npx wrangler r2 bucket create otello-source-archive
```

Deretter brukes `docs/cloudflare-go-live.md` som runbook. Før automatisk deploy aktiveres skal første manuelle deploy, Cron, Workflow, R2 og Time Travel kontrolleres i faktisk Cloudflare-miljø.
