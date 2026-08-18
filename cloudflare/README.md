# Cloudflare production target

Denne katalogen er den aktive Cloudflare-native produksjonsimplementasjonen.

## Tjenester

- **Python Workers + FastAPI** – API og portert finans-/datakildelogikk
- **Workers Static Assets** – React/Vite-dashboard
- **D1** – strukturert produksjonsdatabase
- **R2** – råkilder, NewsWeb-PDF-er og logisk auditsnapshot
- **Cron Triggers** – bounded 30-minutters fast refresh
- **Workflows** – daglig full refresh med retries og R2-arkivering

SQLite-backenden er deterministisk regresjonsreferanse og bootstrap-kilde, ikke produksjonsdatabasen etter cutover.

## Worker API

```text
GET /api/health
GET /api/dashboard/summary
GET /api/dashboard/economic
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
9. R2 logisk auditsnapshot;
10. jobb-/source-health-finalisering.

D1-preflighten krever nå også:

- økonomisk NAV `ready=true` og samme dato som dashboardet;
- minst 20 positive OTEC-volumdager;
- buyback engine må ikke returnere `INSUFFICIENT_VOLUME_HISTORY`.

CVM-årets komprimerte ZIP holdes bounded, og det utpakkede CSV-medlemmet leses som tekststream direkte fra ZIP. Hele CSV-en materialiseres ikke lenger i Worker-minnet.

## Økonomisk NAV

Økonomisk NAV er separat fra CORE/FULL. Worker-pariteten leser kildebelagte cost anchors og cash-FX-ankre fra D1 `source_documents`.

For et cash-anker med dokumentert valutafordeling:

- USD-andel revalueres mot USD/NOK;
- BRL-andel revalueres mot BRL/NOK;
- `UNALLOCATED` rest holdes på ankerverdi.

Ingen ukjent valuta gjettes.

## R2 snapshot

Det logiske auditsnapshotet er chunked og bounded. Det inkluderer nå også:

- `broker_estimate_sets`
- `broker_estimate_values`
- `consensus_snapshots`

Høyfrekvente/re-konstruerbare `company_news`, `market_activity` og `runtime_state` er fortsatt utelatt. D1 Time Travel er full database-recovery.

## D1 bootstrap

`tools/d1_bootstrap.py` støtter:

```text
export          SQLite → deterministisk SQL + manifest
verify          lokal D1/SQLite mot manifest
verify-remote   remote D1 read-only export → eksakt manifestparitet
```

Etter produksjonsimport skal `verify-remote` passere før første Worker cutover godkjennes.

## Deploy

`.github/workflows/deploy-cloudflare.yml`:

1. bygger frontend;
2. renderer produksjonskonfig;
3. applyer remote D1 migrations;
4. deployer Worker/Workflow;
5. tester health, summary, economic NAV og buyback forecast;
6. ruller Worker tilbake til forrige deployerte versjon dersom en senere produksjonsakseptanse feiler.

Worker rollback reverserer ikke D1 migrations. Produksjonsmigreringer skal derfor være additive/bakoverkompatible, og D1 Time Travel brukes ved database-restore.

## Produksjonsressurser

Faktiske ressurser opprettes først ved go-live:

```bash
npx wrangler d1 create otello-nav --location=weur
npx wrangler r2 bucket create otello-source-archive
```

Deretter brukes `docs/cloudflare-go-live.md` som runbook.
