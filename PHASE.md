# Otello Tracker – faseplan

## Status 18.08.2026

Repository-implementasjonen er fullført gjennom **Phase 15.7.2 – final production hardening**. Ingen remote Cloudflare-ressurser eller produksjonsdeploy inngår i denne statusen.

## Cloudflare-migrering

- [x] **15.1** D1-schema og structural parity
- [x] **15.2** deterministisk SQLite → D1 bootstrap/data parity
- [x] **15.3** Python Worker + FastAPI + D1 read API + React Static Assets
- [x] **15.3.1** Cloudflare hardening/query-budget/populated HTTP parity
- [x] **15.3.2** option-aware FULL NAV
- [x] **15.4** scheduled ingestion
- [x] **15.4.1** OTEC intradag + Cron
- [x] **15.4.2** BMOB3 delayed + EOD LAST
- [x] **15.4.3** OTEC EOD/gap recovery
- [x] **15.4.4** NewsWeb incremental
- [x] **15.4.5** dirty-state cash/CORE/FULL NAV
- [x] **15.4.6** bounded EOD/retry/provenance/frontend freshness hardening
- [x] **15.4.7** query/write performance og telemetry
- [x] **15.5** Cloudflare Workflows/full refresh
- [x] **15.6** R2 source archive, NewsWeb-PDF og logiske D1-snapshots
- [x] **15.7** produksjonskonfigurasjon, deploy-workflow og go-live-runbook
- [x] **15.7.1** D1 snapshot-/OTEC recovery-/NewsWeb PDF performance hardening
- [x] **15.7.2** final production hardening

## Phase 15.7.2 – ferdig i kodebasen

### Økonomisk NAV

- [x] CORE/FULL beholdes uendret som regnskaps-/avstemmingsmodell
- [x] separat økonomisk NAV-overlay
- [x] full økonomisk Black-Scholes-verdi vises separat fra recognition-basert opsjonsforpliktelse
- [x] kildebelagt driftskostnadsrun-rate lagres som kuratert data/provenance, ikke Python-konstanter
- [x] dokumentert USD-/BRL-cash revalueres mellom rapporter
- [x] ikke-dokumentert valutafordeling merkes `UNALLOCATED` og gjettes ikke
- [x] SQLite/Worker-matematikk holdes i parity-test
- [x] Economic NAV-panelet ligger direkte i React-layouten, uten DOM-søk/portal

### Bootstrap/preflight

- [x] ren produksjonsbootstrap seeder OTEC-volumhistorikken til buyback-modellen
- [x] SQLite-preflight krever minst 20 positive OTEC-volumdager
- [x] D1-preflight krever samme volumgrunnlag
- [x] begge preflights blokkerer `INSUFFICIENT_VOLUME_HISTORY`
- [x] økonomisk NAV er en eksplisitt D1/full-refresh preflight-kontroll

### Cron/Workflow

- [x] fast Cron fortsatt `*/30 * * * *`
- [x] full Workflow flyttet til `03:35 UTC`
- [x] D1-basert writer-lock forhindrer samtidig fast/full write-path
- [x] lock har expiry slik at krasj ikke kan blokkere systemet permanent
- [x] full-refresh telemetry bruker gjeldende faseetikett

### D1/R2/deploy

- [x] `verify-remote` eksporterer remote D1 read-only og sammenligner mot bootstrap-manifest
- [x] R2 logical audit snapshot inkluderer broker estimates og consensus
- [x] produksjonsakseptanse tester health, summary, economic NAV og buyback forecast
- [x] Worker rollback kjøres dersom post-deploy-akseptansen feiler
- [x] D1-migrasjoner skal fortsatt være additive/bakoverkompatible fordi Worker rollback ikke reverserer D1

### CVM/minne

- [x] CVM ZIP holdes bounded
- [x] utpakket CVM CSV leses som stream fra ZIP-medlemmet
- [x] bare Bemobi-rader beholdes i Python-minne
- [x] CVM metadata kan fortsatt ikke opprette/endre finansielle fakta automatisk

## Produksjon – ikke utført ennå

Følgende er eksterne go-live-steg, ikke en ny kodefase:

- [ ] Workers Paid aktivert
- [ ] remote D1 opprettet
- [ ] R2 bucket opprettet
- [ ] validert produksjonsbootstrap importert
- [ ] remote D1 eksakt avstemt mot manifest
- [ ] GitHub production secrets/variables konfigurert
- [ ] første manuelle deploy gjennomført
- [ ] HTTP-akseptanse grønn
- [ ] fast Cron kontrollert i Workers Logs
- [ ] full Workflow kontrollert
- [ ] R2 råfiler/PDF/snapshot kontrollert
- [ ] D1 Time Travel restore-drill gjennomført
- [ ] eventuelt custom domain/HTTPS kontrollert
- [ ] `CLOUDFLARE_DEPLOY_ENABLED=true` først etter godkjent manuell produksjonsakseptanse

## Finansielt neste kontrollpunkt

### Otello 1H26 – 21.08.2026

Når rapporten publiseres:

1. importer nytt rapportert cash-anker;
2. avstem ONA/balanse;
3. hent ny rapportert opsjonsforpliktelse og eventuelle nye Black-Scholes-input;
4. vurder om Bemobi-salg/retur av proveny endrer recognition/exercisability;
5. oppdater kildebelagte driftskostnadsankre;
6. legg inn ny cash-valutafordeling bare dersom rapporten dokumenterer den;
7. rebuild CORE/FULL og økonomisk NAV;
8. kjør SQLite/D1 parity og produksjonspreflight på nytt.

## Regresjonsprinsipp

SQLite er fortsatt referanseimplementasjon. Cloudflare/D1 skal sammenlignes mot denne for finanslogikk og API-output. Nye investorjusteringer skal legges i økonomisk NAV-overlay eller eksplisitte nye modellversjoner – ikke skjult inn i validerte CORE/FULL-serier.
