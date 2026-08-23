# Cloudflare-produksjon

Denne katalogen inneholder den aktive Cloudflare-native produksjonsimplementasjonen for Otello NAV-oversikten.

## Tjenester

- **Python Workers + FastAPI** – API og finans-/datakildelogikk
- **Workers Static Assets** – React/Vite-dashboard
- **D1** – autoritativ strukturert produksjonsdatabase
- **R2** – råkilder, NewsWeb-PDF-er og logiske revisjonssnapshots
- **Cron Triggers** – bounded fast refresh hvert 30. minutt
- **Workflows** – daglig full refresh med retries og R2-arkivering ved behov

SQLite-backenden er deterministisk regresjonsreferanse, ikke produksjonsdatabasen.

## Sentrale API-er

```text
GET /api/health
GET /api/market/quotes
GET /api/dashboard/summary
GET /api/dashboard/economic
GET /api/dashboard/waterfall
GET /api/dashboard/fx-backtest
GET /api/dashboard/history
GET /api/dashboard/discount-history
GET /api/dashboard/report-status
GET /api/dashboard/runtime-status
GET /api/buybacks/forecast
GET /api/buybacks/dashboard
GET /api/bemobi/dashboard
GET /api/bemobi/consensus
GET /api/bemobi/source-status
```

## Scheduling

```text
Fast refresh:   */30 * * * *
Full Workflow:  35 3 * * * UTC
```

Begge write-paths bruker `runtime_state`-låsen `cloudflare_refresh_writer_lock`. Fast refresh hopper kontrollert over dersom Full Workflow holder låsen. Full Workflow bruker garantert cleanup for å forsøke å frigjøre låsen også ved feil, og låsen har expiry som siste sikkerhetsnett. En startet D1-jobb som fortsatt står `RUNNING` terminaliseres til `FAILED` ved hard Workflow-feil.

## Fast refresh

Fast-banen håndterer lette, inkrementelle oppdateringer:

- OTEC delayed/gap recovery/EOD LAST;
- BMOB3 delayed/EOD LAST;
- NewsWeb incremental;
- berørte cash-/ONA-/CORE-/FULL-lag.

Den er bounded og idempotent. Euronext EOD behandles som `LAST / DIRECT`, ikke som påstått offisiell `CLOSE`.

## Full Workflow

Daglig Workflow håndterer:

1. Norges Bank FX – direkte BRL/NOK og USD/NOK;
2. Life360-markedsdata;
3. B3 COTAHIST;
4. Bemobi/CVM;
5. Bemobi investor-webfakta;
6. NewsWeb reconciliation;
7. NewsWeb PDF og tilbakekjøpsdetaljer;
8. Otello-rapportinnlesing;
9. OTEC recovery/EOD;
10. NAV-oppdatering;
11. D1 production-data preflight;
12. R2 logical snapshot når retention-policy krever det;
13. jobb-/source-health-finalisering.

Preflight skal feile lukket når nødvendige data ikke er klare.

## Økonomisk NAV og valuta

Økonomisk NAV er separat fra CORE/FULL. Worker-pariteten leser kildebelagte kostnadsankre og cash-FX-ankre fra D1.

Daglige BRL/NOK- og USD/NOK-kurser hentes direkte fra Norges Banks åpne EXR-API og lagres med `NORGES_BANK`-proveniens. Historiske ECB-krysskurser beholdes som eldre provenance/fallback, men ECB brukes ikke lenger som løpende produksjonskilde.

Dokumentert USD- og BRL-eksponering revalueres mot løpende valuta. Ufordelt residual skal ikke gis skjult finansielt innhold uten dokumentasjon.

`/api/dashboard/fx-backtest` brukes til historisk kontroll av valutaeffekten.

## Workers Paid / ytelse

Produksjonsrenderer bruker avgrensede grenser:

```text
CPU per invocation:                60 000 ms
Subrequests per invocation:        50 000
Workers Caching, API-entrypoint:   på
Global Workers Caching:            av
Workers Logs sampling:             5 %
Tracing:                           av
```

`assets.run_worker_first` er begrenset til `/api/*`, slik at statiske frontend-assets går direkte gjennom Workers Static Assets.

## R2 snapshot

Det logiske revisjonssnapshotet er chunket og bounded. Det tas søndag og ved månedsslutt. Rå kildefiler/PDF-er med provenance-verdi arkiveres content-addressed når de hentes.

D1 Time Travel er primær korttids-recovery; R2-snapshotet er et ekstra revisjons-/gjenopprettingslag.

## D1-verktøy

`tools/d1_bootstrap.py` støtter fortsatt deterministisk eksport og verifisering:

```text
export          SQLite -> deterministisk SQL + manifest
verify          lokal D1/SQLite mot manifest
verify-remote   remote D1 read-only export -> eksakt manifestparitet
```

Den tidligere engangs-GitHub-workflowen for initial produksjonsbootstrap er fjernet etter go-live. Verktøyet beholdes for referanse, recovery og kontrollerte migreringsoppgaver – ikke som en generell knapp for å overskrive produksjons-D1.

## Deploy

`.github/workflows/deploy-cloudflare.yml`:

1. validerer Cloudflare credentials/resources, custom domain og WAF-gate;
2. bygger frontend;
3. renderer produksjonskonfig;
4. kjører remote D1-migreringer;
5. deployer Worker/Workflow;
6. kjører HTTP-akseptanse mot faktisk produksjon;
7. tester aktive investor-API-er, inkludert NAV, tilbakekjøp, Bemobi og konsensus;
8. ruller Worker tilbake dersom etterkontrollen feiler.

Worker-rollback reverserer ikke D1-migreringer. Nye migreringer skal være additive/bakoverkompatible, og D1 Time Travel brukes ved database-restore.

Se:

- `../docs/architecture.md`
- `../docs/runbook.md`
- `../docs/migration-history.md`
- `../docs/cloudflare-paid-cost-guard.md`
