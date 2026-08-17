# Prosjektstatus

Sist oppdatert: **17.08.2026**

## Nåværende fase – Phase 14: Live market-data og Pi-optimalisering

Phase 14 bygger videre på den ferdige pre-live-plattformen med lettere markedsfeeds, bedre intradag-ferskhet og lavere ressursbruk på Raspberry Pi.

### 14.1 – Lett OTEC-feed

Status: **Ferdig**

- [x] normal intradag bruker Euronext `LAST_15_MINUTES` + `LAST_HOUR`
- [x] full current-day-fil brukes bare ved cold start/gap recovery
- [x] én EOD-finalisering etter Oslo-sessionen
- [x] siste handel lagres som `LAST`, aldri feilmerket som offisiell `CLOSE`
- [x] forrige handelsdag kan ferdigstilles fra samme activity-payload etter nedetid

### 14.2 – Lett BMOB3-feed

Status: **Ferdig**

- [x] B3 offentlig 15-minutters delayed quote brukes intradag
- [x] sluttført delayed `LAST` lagres etter B3-sessionen
- [x] liten offisiell daglig COTAHIST-fil oppgraderer til `CLOSE` når den er publisert
- [x] årlig COTAHIST er flyttet ut av normal intradag/live-prising
- [x] B3-handelskalender og EOD-vinduer håndteres eksplisitt

### 14.3 – Sikkerhet og Raspberry Pi-ytelse

Status: **Ferdig og CI-validert**

- [x] fersk BMOB3 kan oppdatere dagens indikative NAV selv før OTEC har handlet samme dag
- [x] eksisterende NAV-formel/lookbacks beholdes; `MIXED` viser ulike komponentdatoer eksplisitt
- [x] 30-minutters fast refresh hopper over full cash-rebuild når modellinputene er uendret
- [x] daglig fullrefresh primer samme dirty-state slik at neste fastsyklus ikke gjentar rebuild
- [x] statiske kuraterte manifests seeds bare når innhold/fingerprint er endret
- [x] NewsWeb buyback-refresh bruker automatisk siste dato minus sikkerhetsoverlapp
- [x] CVM inneværende år refreshes løpende; foregående år kontrolleres periodisk i stedet for daglig
- [x] OTEC delayed payloads har immutabel kilde/provenance per payload
- [x] NewsWeb JSON/PDF har eksplisitte størrelsesgrenser
- [x] Nginx har rate limiting, sikkerhetsheadere og proxy-timeouts
- [x] containere bruker `no-new-privileges`
- [x] CI kontrollerer Python dependency-konsistens, produksjons-NPM audit og Nginx-konfigurasjon
- [x] nye regresjonstester dekker dirty-state, mixed-date NAV, CVM, NewsWeb og OTEC provenance

Bevisst ikke endret i 14.3: NAV-formelen, buyback-estimator/backtest og automatisk backup-retention.

## Pre-live-plattform – Phase 13

Phase 13 gjorde repoet testbart og eksplisitt deploybart til Raspberry Pi-produksjon.

### 13.1 – Produksjons-bootstrap og preflight

Status: **Ferdig**

- [x] ren database kan migreres og seeds med kuraterte historiske fakta
- [x] full ECB BRL/NOK + USD/NOK fra 10.02.2021
- [x] alle B3 COTAHIST-år fra 2021 til inneværende år
- [x] historisk OTEC importeres fra validert Euronext-/Investing-CSV
- [x] streng `preflight --strict`
- [x] SQLite-integritet og migreringsnivå
- [x] kontroll av OTEC/BMOB3/FX historisk dekning
- [x] kontroll av FX-vindu for hvert rapporterte ikke-NOK cash-anker
- [x] NewsWeb/buyback-dekning
- [x] cash/CORE/ONA/FULL og dashboard-readiness

Dokumentasjon: `docs/pre-live-hardening.md`.

### 13.2 – Scheduler, ytelse, jobbstatus og backup

Status: **Ferdig**

- [x] lett fast refresh hvert 30. minutt
- [x] delayed OTEC + inkrementell NewsWeb i fastløpet
- [x] ingen B3-årsfil/ECB/CVM/MFN-fullarbeid hvert 30. minutt
- [x] full refresh standard én gang per døgn
- [x] full/fast/backup-jobber lagres i `job_runs`
- [x] SQLite backup-API mot levende WAL-database
- [x] backup må passere `PRAGMA integrity_check`
- [x] standard backupkatalog `/data/backups`

Kjent driftsoppgave: automatisk retention/sletting av gamle backuper er ikke aktivert. Diskforbruk skal overvåkes, og restore skal testes på faktisk Pi før full driftsklar-erklæring.

### 13.3 – Datoferskhet og GUI

Status: **Ferdig**

- [x] OTEC/BMOB3/BRL-NOK komponentdatoer i dashboard-API
- [x] `ALIGNED`, `MIXED`, `STALE`, `UNKNOWN`
- [x] MIXED markeres som indikativt uten å endre NAV-beregningen
- [x] GUI oppdaterer data automatisk hvert 2. minutt
- [x] gammel rapportert Bemobi-eierandel vises ikke som dagens prosent
- [x] verifisert Bemobi-aksjeantall brukes fortsatt i NAV

### 13.4 – Reproducerbarhet, tidssone og produksjons-CI

Status: **Ferdig og CI-validert**

- [x] frontend direkte avhengigheter pinnet
- [x] `package-lock.json` generert fra GitHub CI
- [x] frontend bruker `npm ci` i Docker og CI
- [x] backend direkte Python-avhengigheter pinnet til testede versjoner
- [x] eksplisitt `Europe/Oslo` i backend/scheduler
- [x] backend-image inkluderer `tzdata`
- [x] CI bygger faktiske produksjons-Docker-images, ikke bare Compose-konfigurasjon
- [x] README og produksjonsinstruksjoner synkronisert

## Funksjonell historikk

Følgende hoveddeler er ferdige fra tidligere faser:

- [x] FastAPI + React/TypeScript + Docker Compose/nginx
- [x] SQLite med versjonerte migreringer, WAL, FK og provenance
- [x] historiske Otello-rapportankre fra 2021
- [x] BMOB3 fra B3 og BRL/NOK/USD/NOK fra ECB
- [x] OTEC historisk kurshåndtering og Euronext-overlapp
- [x] daglig cash og CORE NAV
- [x] FULL NAV med øvrige nettoeiendeler/-forpliktelser
- [x] NewsWeb fullhistorikk fra 2020 og klassifisering
- [x] originale NewsWeb buyback-transaksjonsvedlegg og daglig cash-timing
- [x] historiske aksjetall/kanselleringer og buyback-programmer
- [x] CVM Bemobi-nyheter
- [x] Bemobi-utbytte/JCP og skattebehandling
- [x] Euronext delayed OTEC LAST
- [x] B3 delayed BMOB3 LAST + offisiell daglig CLOSE
- [x] Safe Harbour-basert buyback-prognose og walk-forward-backtest
- [x] live dashboard med NAV, rabatt, buyback, Bemobi og modellstatus

## Neste obligatoriske produksjonsporter

### A. Faktisk Raspberry Pi-database

Når Pi-en er tilgjengelig:

1. `docker compose build`
2. bootstrap ren `/data/otello.db` med den validerte historiske OTEC-filen
3. kjør `python -m app.jobs.preflight --strict`
4. verifiser `READY`
5. start stacken
6. kontroller `job_runs`, scheduler, backup og GUI over minst ett døgn
7. gjør en faktisk restore-test fra backup

### B. Otello 1H26 – 21.08.2026

Dagens cash/ONA etter siste rapportanker kan legitimt være `FORECAST_PARTIAL`/estimert. Når 1H26 publiseres:

1. importer nye rapporterte cash-/balanseankre
2. avstem ONA
3. rebuild CORE/FULL
4. kontroller residualer og share count
5. kjør preflight på nytt

Før dette skal dashboardet ikke late som dagens cash/ONA er rapportert.

## Etter pre-live

Når produksjonsportene over er bestått kan neste funksjonelle utvikling fortsette, blant annet:

- meglerkonsensus før Bemobi-rapporter
- aksjonærdata der lovlig og teknisk forsvarlig
- e-post-/ukerapporter
- bedre navigasjon/undersider i GUI
- varsling på source/job health
- sikker automatisk backup-retention når restore-rutinen er etablert
