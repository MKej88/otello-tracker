# Prosjektstatus

Sist oppdatert: **17.08.2026**

## Nåværende fase – Phase 15: D1 og Worker-migrering

Kjernemodellen og live-feedene er ferdige. Produksjonsmålet er **Cloudflare-native**.

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

Status: **Erstattet som produksjonsmål av 14.5**

Docker Compose beholdes som lokal/regresjonsreferanse under Cloudflare-migreringen.

### 14.5 – Cloudflare-native målarkitektur

Status: **Ferdig som arkitekturvalg**

- [x] Cloudflare valgt som produksjonsplattform
- [x] Python Workers + FastAPI valgt for API/forretningslogikk
- [x] Workers Static Assets valgt for React/Vite
- [x] D1 valgt som autoritativ produksjonsdatabase
- [x] R2 valgt for PDF/råkilder/arkiv
- [x] Cron Triggers valgt for fast refresh
- [x] Workflows/scheduled jobs valgt for tyngre refresh/retries
- [x] Cloudflare Containers avvist som autoritativ SQLite-disk
- [x] Cloudflare deploy/runbook dokumentert
- [ ] opprett faktiske D1/R2/Worker-ressurser – gjøres når migreringen er klar for remote deploy
- [ ] koble GitHub/Cloudflare deploy – go-live-fase

## Phase 15 – D1 og Worker-migrering

### 15.1 – D1 schema og structural parity

Status: **Ferdig og CI-validert**

- [x] konsolidert D1-schema genereres deterministisk fra fullt migrert SQLite-referanse
- [x] `schema_migrations` holdes utenfor fordi Wrangler/D1 fører migreringshistorikken
- [x] alle tabeller og endelige felt fra migrasjon 0001–0016 er med
- [x] foreign keys, delete/update-regler og constraints er bevart
- [x] eksplisitte/partial/unique indekser er bevart
- [x] NewsWeb/buyback-triggerne er bevart
- [x] separat D1-migrering for stabile sources/instruments
- [x] schema drift-check i CI
- [x] parity-tester for tabeller, kolonner, foreign keys, indekser og triggere
- [x] lokal Wrangler D1 kjører begge migrations uten feil
- [x] `PRAGMA foreign_key_check` er tom etter migrering
- [x] 12 sources og 2 instrumenter seeds i lokal D1
- [x] backend-regresjonspakken passerer med D1 parity-testene inkludert

Dokumentasjon: `docs/d1-migration.md`.

### 15.2 – Historisk bootstrap og data parity

Status: **Bootstrap-pipeline ferdig og CI-validert; produksjonssnapshot/remote import venter på faktisk D1-ressurs**

- [x] eksportere en validert SQLite-referansesnapshot til portabel D1-SQL
- [x] bruke read-only snapshot-transaksjon og stoppe ved integrity/FK/schema-feil
- [x] deterministisk manifest med radtall og SHA-256 per historikktabell
- [x] global logisk SHA-256 uavhengig av SQLite page/WAL-layout
- [x] kontrollere CORE/FULL NAV, market/FX coverage, cash, ONA, share count og Bemobi-holding
- [x] kontrollere weekly/daily buyback-antall, aksjer og beløp
- [x] bevare source/instrument-ID-er og migreringsmetadata nøyaktig
- [x] importere CI-referansen gjennom ekte lokal Wrangler D1
- [x] eksakt logical parity + `PRAGMA foreign_key_check` etter lokal D1-import
- [x] bootstrap-pakken holdes utenfor Git
- [x] gamle `job_runs`, `source_health` og `runtime_state` resettes med vilje
- [ ] eksportere den konkrete løpende produksjons-/referanse-SQLite-filen når cutover-snapshot tas
- [ ] importere samme validerte pakke til faktisk remote `otello-nav` D1 når ressursen er opprettet

Dokumentasjon: `docs/d1-bootstrap.md`.

### 15.3 – Worker API og D1 repository

Status: **Neste**

- [ ] Cloudflare Python Worker/FastAPI med eksisterende dashboard API-kontrakter
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

- [ ] Workers plan/limits verifisert mot reell CPU-bruk
- [ ] Cloudflare secrets
- [ ] GitHub → Cloudflare auto-deploy
- [ ] custom domain og HTTPS
- [ ] D1 restore/Time Travel-test
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
