# Prosjektstatus

Sist oppdatert: **17.08.2026**

## Nåværende fase – Phase 14/15: Cloudflare-native produksjon

Kjernemodellen og live-feedene er ferdige. Produksjonsmålet er nå spesifikt **Cloudflare**.

### 14.1 – Lett OTEC-feed

Status: **Ferdig**

- [x] Euronext `LAST_15_MINUTES` + `LAST_HOUR`
- [x] gap recovery ved behov
- [x] EOD-finalisering

### 14.2 – Lett BMOB3-feed

Status: **Ferdig**

- [x] B3 15-minutters delayed quote
- [x] EOD LAST
- [x] daglig COTAHIST CLOSE

### 14.3 – Sikkerhet og produksjonsytelse

Status: **Ferdig og CI-validert**

- [x] mixed-date live NAV
- [x] dirty-state cash
- [x] inkrementell NewsWeb/CVM
- [x] immutabel provenance
- [x] responsgrenser og hardening

### 14.4 – Generisk cloud-grunnlag

Status: **Erstattes som produksjonsmål av 14.5**

Det generiske VM/Docker-oppsettet var nyttig for å skille prosjektet fra lokal maskinvare, men er ikke riktig sluttdesign når valgt leverandør er Cloudflare.

Docker Compose beholdes som lokal/regresjonsreferanse under migreringen.

### 14.5 – Cloudflare-native målarkitektur

Status: **Pågår**

- [x] Cloudflare valgt som produksjonsplattform
- [x] Workers Static Assets valgt for React/Vite
- [x] D1 valgt som autoritativ produksjonsdatabase
- [x] R2 valgt for PDF/råkilder/arkiv
- [x] Cron Triggers valgt for fast refresh
- [x] Workflows/scheduled jobs valgt for tyngre refresh/retries
- [x] Cloudflare Containers avvist som autoritativ SQLite-disk pga ephemeral disk
- [x] generic persistent-disk production env fjernes
- [x] Cloudflare deploy/runbook dokumentert
- [ ] opprett faktisk Workers/Wrangler-prosjekt
- [ ] opprett D1 database/bindings
- [ ] opprett R2 bucket/binding
- [ ] koble GitHub/Cloudflare deploy

## Phase 15 – D1 og Worker-migrering

### 15.1 – D1 schema

- [ ] konverter dagens SQLite migrations til D1-kompatible migrations
- [ ] bevare tabell-/feltsemantikk og finansielle constraints
- [ ] lage schema parity-test

### 15.2 – Historisk bootstrap til D1

- [ ] eksportere validert SQLite-referansedatabase til importformat
- [ ] importere historiske OTEC/BMOB3/FX/cash/buyback/NAV-data
- [ ] verifisere row counts og kontrollsummer/nøkkeltall

### 15.3 – Worker API

- [ ] Cloudflare Worker med eksisterende dashboard API-kontrakter
- [ ] D1 repository/data-access-lag
- [ ] summary/history/forecast parity mot referansebackend
- [ ] React static assets på samme Worker/custom domain

### 15.4 – Cloudflare scheduled ingestion

- [ ] OTEC delayed/EOD
- [ ] BMOB3 delayed/EOD
- [ ] NewsWeb incremental
- [ ] dirty-state cash/NAV
- [ ] Cron Trigger `*/30 * * * *`

### 15.5 – Full refresh Workflows

- [ ] ECB
- [ ] B3/CVM tyngre refresh
- [ ] NewsWeb reconciliation
- [ ] source-specific retries
- [ ] data-health/preflight

### 15.6 – R2 og kildearkiv

- [ ] NewsWeb PDF
- [ ] rå CSV/ZIP ved behov
- [ ] historiske importfiler
- [ ] eksport/snapshot

### 15.7 – Cloudflare go-live

- [ ] Workers Paid/limits verifisert mot reell CPU-bruk
- [ ] Cloudflare secrets
- [ ] GitHub → Cloudflare auto-deploy
- [ ] custom domain og HTTPS
- [ ] D1 Time Travel/restore test
- [ ] observability/logging
- [ ] end-to-end preflight

## Produksjonsplattform – Phase 13

Phase 13-funksjonaliteten beholdes som referanse og regresjonsgrunnlag:

- [x] database schema/migrations
- [x] produksjonsbootstrap/preflight
- [x] scheduler/job status
- [x] freshness
- [x] dependency/CI hardening

Under Cloudflare-migreringen skal nye resultater sammenlignes mot denne implementasjonen slik at NAV-formel, buyback-modell og datakvalitet ikke endres utilsiktet.

## Funksjonell historikk

- [x] React/TypeScript dashboard
- [x] FastAPI referansebackend
- [x] SQLite referansedatabase med provenance
- [x] historiske Otello-rapportankre
- [x] BMOB3/B3 og ECB FX
- [x] OTEC Euronext delayed/historikk
- [x] cash, CORE og FULL NAV
- [x] NewsWeb og buybacks
- [x] CVM/Bemobi-utbytte/JCP
- [x] Safe Harbour buyback-prognose/backtest

## Finansielt neste steg

### Otello 1H26 – 21.08.2026

Når rapporten publiseres:

1. importer nye rapporterte cash-/balanseankre;
2. avstem ONA;
3. rebuild CORE/FULL;
4. kontroller residualer/share count;
5. bruk disse som nye referanseverdier for Cloudflare/D1 parity-testene.
