# Prosjektstatus

Sist oppdatert: **17.08.2026**

## Nåværende fase – Phase 14: Live market-data og cloud-produksjon

Phase 14 bygger videre på produksjonsplattformen med lettere markedsfeeds, bedre intradag-ferskhet, lavere ressursbruk og et provider-nøytralt cloud-oppsett.

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

### 14.3 – Sikkerhet og produksjonsytelse

Status: **Ferdig og CI-validert**

- [x] fersk BMOB3 kan oppdatere dagens indikative NAV selv før OTEC har handlet samme dag
- [x] eksisterende NAV-formel/lookbacks beholdes; `MIXED` viser ulike komponentdatoer eksplisitt
- [x] fast refresh hopper over full cash-rebuild når modellinputene er uendret
- [x] fullrefresh primer samme dirty-state slik at neste fastsyklus ikke gjentar rebuild
- [x] statiske kuraterte manifests seeds bare når innhold/fingerprint er endret
- [x] NewsWeb buyback-refresh bruker siste dato minus sikkerhetsoverlapp
- [x] CVM inneværende år refreshes løpende; foregående år kontrolleres periodisk
- [x] OTEC delayed payloads har immutabel kilde/provenance per payload
- [x] NewsWeb JSON/PDF har eksplisitte størrelsesgrenser
- [x] Nginx har rate limiting, sikkerhetsheadere og proxy-timeouts
- [x] containere bruker `no-new-privileges`
- [x] CI kontrollerer Python dependency-konsistens, production NPM audit og Nginx-konfigurasjon

Bevisst ikke endret i 14.3: NAV-formelen, buyback-estimator/backtest og automatisk backup-retention.

### 14.4 – Cloud-first produksjonsoppsett

Status: **Implementert – merge kun ved grønn CI**

- [x] repoet er ryddet for tidligere lokal maskinvare-spesifikk produksjonsplan
- [x] én aktiv cloud app-host/region med Docker Compose er standard produksjonsarkitektur
- [x] persistent host-path er konfigurerbar via `DATA_DIR`
- [x] separat `.env.production.example` for cloud-produksjon
- [x] bare web skal eksponeres; API forblir privat på Docker-nettet
- [x] HTTPS termineres hos cloud edge/load balancer/reverse proxy
- [x] cloud-runbook i `docs/cloud-deployment.md`
- [x] produksjonsport i `docs/production-readiness.md`
- [x] SQLite-begrensningen mot horisontal multi-host skalering er eksplisitt dokumentert
- [x] off-host backup/snapshot er produksjonskrav i tillegg til lokale SQLite-snapshots
- [x] CI validerer `.env.production.example` mot Compose
- [ ] provider-spesifikk deploy fra GitHub Actions – avventer valg av cloud-provider
- [ ] automatisk object-storage backup/retention – avventer valg av cloud-provider

## Produksjonsplattform – Phase 13

Phase 13 gjorde repoet testbart, reproducerbart og eksplisitt deploybart som containerisert produksjonsapplikasjon.

### 13.1 – Produksjons-bootstrap og preflight

Status: **Ferdig**

- [x] ren database kan migreres og seeds med kuraterte historiske fakta
- [x] full ECB BRL/NOK + USD/NOK fra 10.02.2021
- [x] alle B3 COTAHIST-år fra 2021 til inneværende år
- [x] historisk OTEC importeres fra validert Euronext-/Investing-CSV
- [x] streng `preflight --strict`
- [x] SQLite-integritet og migreringsnivå
- [x] kontroll av OTEC/BMOB3/FX historisk dekning
- [x] NewsWeb/buyback-dekning
- [x] cash/CORE/ONA/FULL og dashboard-readiness

Dokumentasjon: `docs/production-readiness.md`.

### 13.2 – Scheduler, ytelse, jobbstatus og backup

Status: **Ferdig**

- [x] lett fast refresh hvert 30. minutt
- [x] full refresh standard én gang per døgn
- [x] full/fast/backup-jobber lagres i `job_runs`
- [x] SQLite backup-API mot levende WAL-database
- [x] backup må passere `PRAGMA integrity_check`
- [x] standard backupkatalog `/data/backups`

### 13.3 – Datoferskhet og GUI

Status: **Ferdig**

- [x] OTEC/BMOB3/BRL-NOK komponentdatoer i dashboard-API
- [x] `ALIGNED`, `MIXED`, `STALE`, `UNKNOWN`
- [x] MIXED markeres som indikativt uten å endre NAV-beregningen
- [x] GUI oppdaterer data automatisk hvert 2. minutt
- [x] gammel rapportert Bemobi-eierandel vises ikke som dagens prosent

### 13.4 – Reproducerbarhet, tidssone og produksjons-CI

Status: **Ferdig og CI-validert**

- [x] låste frontend-avhengigheter og `npm ci`
- [x] pinnede direkte Python-avhengigheter
- [x] eksplisitt `Europe/Oslo`
- [x] faktiske produksjons-Docker-images bygges i CI

## Funksjonell historikk

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

### A. Cloud production

1. velg endelig cloud-provider/host;
2. opprett persistent disk og sett `DATA_DIR`;
3. bygg image og bootstrap `/data/otello.db`;
4. kjør `preflight --strict` og verifiser `READY`;
5. start stacken bak HTTPS;
6. bekreft at bare web er eksternt eksponert;
7. kontroller `job_runs`, scheduler og backup gjennom minst ett døgn;
8. restart/redeploy og bekreft at persistent database består;
9. gjør faktisk restore-test;
10. aktiver off-host snapshot/object-storage backup.

### B. Otello 1H26 – 21.08.2026

Når rapporten publiseres:

1. importer nye rapporterte cash-/balanseankre;
2. avstem ONA;
3. rebuild CORE/FULL;
4. kontroller residualer og share count;
5. kjør preflight på nytt.

Før dette kan dagens cash/ONA legitimt være `FORECAST_PARTIAL`/estimert.

## Etter cloud-go-live

- meglerkonsensus før Bemobi-rapporter
- aksjonærdata der lovlig og teknisk forsvarlig
- e-post-/ukerapporter
- bedre navigasjon/undersider i GUI
- varsling på source/job health
- provider-spesifikk GitHub Actions deploy
- automatisk off-host backup/retention
