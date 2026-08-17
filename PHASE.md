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

- [x] D1 baseline-schema ble generert deterministisk fra migrert SQLite-referanse
- [x] `schema_migrations` holdes utenfor fordi Wrangler/D1 fører migreringshistorikken
- [x] baseline inneholder opprinnelig struktur gjennom SQLite 0016
- [x] senere schemaendringer legges til som additive D1-migreringer; baseline `0001` er frosset
- [x] current schema parity er validert gjennom SQLite 0017 / D1 0004
- [x] foreign keys, delete/update-regler og constraints er bevart
- [x] eksplisitte/partial/unique indekser er bevart
- [x] NewsWeb/buyback-triggerne er bevart
- [x] separat D1-migrering for stabile sources/instruments
- [x] schema drift-check i CI
- [x] parity-tester for tabeller, kolonner, foreign keys, indekser og triggere
- [x] lokal Wrangler D1 kjører migrations uten feil
- [x] `PRAGMA foreign_key_check` er tom etter migrering
- [x] 12 sources og 2 instrumenter seeds i lokal D1

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

Status: **Ferdig og CI-validert lokalt; remote deploy venter på faktisk D1-ressurs**

- [x] Cloudflare Python Worker/FastAPI med eksisterende dashboard API-kontrakter
- [x] read-only D1 repository/data-access-lag med parameterbinding
- [x] D1 readiness i `/api/health`
- [x] eksakt `summary` parity mot referansebackend
- [x] eksakt `history` parity mot referansebackend
- [x] eksakt `buybacks/forecast` parity mot referansebackend
- [x] uendret Safe Harbour-/buyback methodology version og punktestimatnivå
- [x] Oslo Børs-kalender parity mot referanseimplementasjonen
- [x] Python Worker dry-run build i CI
- [x] faktisk lokal `workerd` HTTP-smoketest mot D1
- [x] React/Vite koblet til samme Worker med Workers Static Assets
- [x] `/api/*` kjøres Worker-first mens frontend-assets serveres direkte
- [x] SPA-fallback for frontend-ruter
- [ ] deploye mot faktisk remote `otello-nav` etter Phase 15.2 cutover-snapshot/import

Dokumentasjon: `docs/worker-api.md`.

### 15.3.1 – Cloudflare hardening før ingestion

Status: **Ferdig og CI-validert**

- [x] buyback forecast bruker én bounded OTEC activity-read i stedet for to D1-queries per historisk programuke
- [x] eksplisitt query-budget-regresjonstest på ready-path
- [x] bounded activity-vindu beholder alltid de nyeste radene før kronologisk modellberegning
- [x] D1-spesifikke ytelsesindekser for buyback-program og NAV-serie
- [x] populated SQLite → D1 → `workerd` → HTTP parity-test i CI
- [x] eksakt JSON-sammenligning av summary/history/forecast mot referansebackend
- [x] Cloudflare `_headers` for statiske assets med CSP og browser-hardening
- [x] API-genererte Worker-responser får egne sikkerhetsheadere
- [x] korte cachevinduer på summary og lengre cachevinduer på history/forecast
- [x] fingerprintede Vite-assets får immutable langtids-cache
- [x] README/Worker-dokumentasjon oppdatert til faktisk fase

### 15.3.2 – Opsjonsforpliktelse i FULL NAV

Status: **Ferdig og CI-validert på implementasjonen**

- [x] kuraterte vilkår for 4,1m kontantoppgjorte Otello-opsjoner fra 15.09.2025
- [x] strike NOK 12,5637 med eksplisitt nedjustering for senere betalte Otello-utdelinger
- [x] Black-Scholes mark-to-market koblet til historisk/løpende OTEC-kurs
- [x] rapportert ONA dekomponeres som `base ONA ex option + Bemobi receivable - option liability`
- [x] 31.12.2025 avstemmes eksakt mot rapportert opsjonsforpliktelse på USD 314k
- [x] historisk ONA-bane før tildelingsdato beholdes uendret
- [x] tildeling → 31.12.2025 rekonstrueres mot rapportert årssluttanker
- [x] etter 31.12.2025 holdes recognition factor konstant inntil ny rapport eller kvalifiserende Bemobi-salg gir nytt evidensgrunnlag
- [x] siste rapporterte risikofri rente/volatilitet brukes etter siste rapport og merkes forecast
- [x] opsjonsforpliktelsen faller/stiger med mark-to-market og trekkes eksplisitt fra FULL NAV
- [x] SQLite-migrasjon 0017 og D1-migrasjon 0004
- [x] D1 bootstrap/schema/data parity inkluderer opsjonsfeltene
- [x] populated D1 → Worker → HTTP parity fortsatt grønn
- [x] CORE NAV og buyback-metodikk er uendret

**Konsekvens:** FULL NAV og historisk rabatt fra 15.09.2025 kan endres når referansedatabasen bygges på nytt. Det er tilsiktet fordi opsjonsforpliktelsen nå verdsettes eksplisitt per dato i stedet for bare å ligge implisitt i rapportert total gjeld på rapportdatoen.

Dokumentasjon: `docs/option-liability.md`.

### 15.4 – Cloudflare scheduled ingestion

Status: **Pågår – 15.4.1–15.4.4 er ferdige og CI-validerte**

#### 15.4.1 – OTEC intradag + Cron

- [x] eget D1 write-repository med parameterbinding og idempotente source/market-price writes
- [x] Euronext `LAST_15_MINUTES` som Worker-native fetch + D1-write
- [x] `LAST_HOUR` som overlapp/fallback når 15-minuttersvinduet ikke inneholder OTEC
- [x] eksakt OTEC ISIN / XOSL / NOK / MONE-filter bevart fra referanseimplementasjonen
- [x] `LAST` / `DIRECT`-semantikk og provenance bevart
- [x] intradag-ZIP er størrelsesbegrenset og CSV-medlemmet leses sekvensielt fra ZIP-strømmen
- [x] `job_runs` for planlagt innhenting
- [x] Python Worker `scheduled(self, controller, env, ctx)`
- [x] Cron Trigger `*/30 * * * *`
- [x] backend-regresjon, D1 parity, Python Worker dry-run og faktisk `workerd` HTTP parity grønn

#### 15.4.2 – BMOB3 delayed + EOD LAST

- [x] B3 delayed JSON som Worker-native fetch + D1-write
- [x] 15-minutters effective timestamp bevart fra referanseimplementasjonen
- [x] B3-handelskalender og Ash Wednesday-vindu portert til Worker
- [x] bounded 256 KiB JSON-respons
- [x] `LAST` / `DIRECT`-semantikk og provenance bevart
- [x] idempotent EOD LAST etter 19:15 São Paulo
- [x] EOD LAST merkes eksplisitt som forsinket webkurs, ikke offisiell COTAHIST `CLOSE`
- [x] COTAHIST CLOSE beholdes som sterkere kilde i full refresh
- [x] BMOB3 koblet til samme 30-minutters Cron som OTEC
- [x] kildefeil isoleres slik at én feed kan gi `PARTIAL` uten å stoppe den andre
- [x] Worker-subrequest sender ikke forbudt `Connection` hop-by-hop-header
- [x] egen regresjonstest låser Cloudflare-headerkravet
- [x] backend-regresjon, D1 parity, Python Worker dry-run og faktisk `workerd` HTTP parity grønn

#### 15.4.3 – OTEC EOD + gap recovery

- [x] referansens 75-minutters overlap/gap-detection er portert til D1/Worker
- [x] `CURRENT_TRADING_DAY` brukes bare ved kaldstart eller OTEC-poll-gap over 75 minutter
- [x] komprimert recovery-ZIP har hard 32 MiB grense som kontrolleres før body-buffering når `Content-Length` finnes
- [x] utpakket CSV leses sekvensielt fra ZIP-strømmen; bare OTEC-rader beholdes i Python
- [x] normal EOD etter 16:45 Oslo finaliseres fra frisk rolling-window-dekning og siste D1-handel uten ny dagsfil
- [x] EOD beholdes som `LAST` / `DIRECT` og merkes eksplisitt som siste rapporterte handel, ikke offisiell `CLOSE`
- [x] for stor recovery-payload feiler kontrollert slik at scheduled job kan bli `PARTIAL` fremfor Worker-OOM
- [x] recovery-payload over Worker-grensen er eksplisitt flyttet til R2/Workflow-sporet i 15.5/15.6
- [x] backend-regresjon, D1 parity, Python Worker dry-run og faktisk `workerd` HTTP parity grønn

#### 15.4.4 – NewsWeb incremental

- [x] NewsWeb API-klient portert til Python Worker
- [x] bounded 5 MiB JSON-respons med Content-Length-sjekk før body-lesing når tilgjengelig
- [x] issuer 7759 / OTEC / XOSL-validering bevart
- [x] recursive overflow-splitting og corrected/superseded-filter bevart
- [x] 14-dagers overlappende history archive til source_documents/company_news
- [x] full meldingstekst lagres ikke; SHA-256 + metadata + strukturerte fakta beholdes
- [x] 21-dagers overlappende buyback-refresh
- [x] ukentlig parser er lik referansen for dokumenterte 2023–2025 ordlydsvarianter
- [x] buyback_programs, weekly buybacks, bekreftet fallback-cash og treasury/outstanding shares skrives idempotent til D1
- [x] kildeprioritet bevart: NewsWeb overskriver ikke motstridende sterkere Euronext-fakta
- [x] PDF/daglige buyback-transaksjoner er eksplisitt utsatt til full refresh/R2 i 15.5/15.6
- [x] NewsWeb history + buybacks koblet til 30-minutters Cron
- [x] test skriver mot database bygget fra faktiske D1-migreringer og verifiserer idempotens/source priority
- [x] backend-regresjon, D1 parity, Python Worker dry-run og faktisk `workerd` HTTP parity grønn

#### Gjenstår i 15.4

- [ ] dirty-state cash/NAV på D1, inkludert option-aware FULL NAV

Dokumentasjon: `cloudflare/README.md`.

### 15.5 – Full refresh Workflows

- [ ] ECB
- [ ] B3/CVM tyngre refresh
- [ ] NewsWeb reconciliation
- [ ] source-specific retries
- [ ] data-health/preflight
- [ ] OTEC recovery via R2/Workflow når dagsfil overskrider fast-path-grensen

### 15.6 – R2 og kildearkiv

- [ ] NewsWeb PDF og daglige buyback-transaksjoner
- [ ] rå CSV/ZIP ved behov, inkludert store OTEC recovery-filer
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

Under Cloudflare-migreringen skal nye resultater sammenlignes mot denne implementasjonen slik at finanslogikk, buyback-modell og datakvalitet ikke endres utilsiktet. Phase 15.3.2 er et eksplisitt og kildebegrunnet unntak: FULL NAV er forbedret med daglig opsjonsforpliktelse.

## Funksjonell historikk

- [x] React/TypeScript dashboard
- [x] FastAPI referansebackend
- [x] SQLite referansedatabase med provenance
- [x] historiske Otello-rapportankre
- [x] BMOB3/B3 og ECB FX
- [x] OTEC Euronext delayed/historikk
- [x] cash, CORE og FULL NAV
- [x] option-aware FULL NAV fra 15.09.2025
- [x] NewsWeb og buybacks
- [x] CVM/Bemobi-utbytte/JCP
- [x] Safe Harbour buyback-prognose/backtest

## Finansielt neste steg

### Otello 1H26 – 21.08.2026

Når rapporten publiseres:

1. importer nye rapporterte cash-/balanseankre;
2. avstem ONA;
3. hent og avstem ny rapportert opsjonsforpliktelse og eventuelle oppdaterte Black-Scholes-input;
4. kontroller om Bemobi-salg/retur av proveny har endret exercisability/recognition;
5. rebuild CORE/FULL og historisk rabatt;
6. kontroller residualer/share count;
7. bruk disse som nye referanseverdier for Cloudflare/D1 parity-testene.
