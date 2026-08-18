# Otello Tracker – faseplan

## Status 18.08.2026

Repository-implementasjonen er fullført gjennom **Phase 15.7.2 – final production hardening**, med påfølgende Workers Paid-, kostnads- og produksjonsakseptanse-herding. Cloudflare Workers Paid er aktivert. Remote D1/R2 og første produksjonsdeploy er fortsatt eksterne go-live-steg.

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
- [x] **Workers Paid-herding** API-only cache, kostnadsgrenser, D1-indekser, redusert observability og ukentlig/månedsslutt auditsnapshot
- [x] **Produksjonsakseptanse-herding** obligatorisk HTTPS/public URL, WAF-gate, frontend/history/economic/FX-backtest/buyback HTTP-kontroll og rollback

## Ferdig i kodebasen

### Økonomisk NAV og valuta

- [x] CORE/FULL beholdes uendret som regnskaps-/avstemmingsmodell
- [x] separat økonomisk NAV-overlay
- [x] full økonomisk Black-Scholes-verdi vises separat fra recognition-basert opsjonsforpliktelse
- [x] kildebelagt driftskostnadsrun-rate lagres som kuratert data/provenance, ikke Python-konstanter
- [x] dokumentert USD-/BRL-cash revalueres mellom rapporter
- [x] cash-residual vises separat som estimert NOK uten å endre konservativ NAV-logikk
- [x] historisk valuta-backtest med cash-FX som primært valideringsmål
- [x] SQLite/Worker-matematikk holdes i parity-test
- [x] Economic NAV-panelet ligger direkte i React-layouten

### Bootstrap/preflight

- [x] ren produksjonsbootstrap seeder OTEC-volumhistorikken til buyback-modellen
- [x] historiske OTEC-priser må komme fra validert Euronext-CSV eller manuell Investing.com-eksport; de skrapes ikke skjult
- [x] SQLite-preflight krever minst 20 positive OTEC-volumdager
- [x] D1-preflight krever samme volumgrunnlag
- [x] begge preflights blokkerer `INSUFFICIENT_VOLUME_HISTORY`
- [x] økonomisk NAV er en eksplisitt D1/full-refresh preflight-kontroll
- [x] produksjonsbootstrap lager deterministisk SQL + manifest og blokkeres dersom preflight ikke er klar
- [x] `verify-remote` avstemmer remote D1 eksakt mot bootstrap-manifestet

### Cron/Workflow

- [x] fast Cron `*/30 * * * *`
- [x] full Workflow `03:35 UTC`
- [x] D1-basert writer-lock forhindrer samtidig fast/full write-path
- [x] lock har expiry slik at krasj ikke kan blokkere systemet permanent
- [x] fast refresh unngår unødvendige OTEC-nettkall utenfor relevant handelsvindu
- [x] full-refresh telemetry og retries er bounded

### Workers Paid / ytelse og kostnad

- [x] Workers Paid aktivert på kontoen
- [x] produksjonsgrense 60 000 ms CPU per invocation
- [x] produksjonsgrense 500 subrequests per invocation
- [x] Workers Caching kun på API-entrypointen
- [x] Static Assets går utenom API-entrypointen
- [x] Workers Logs samples 5 %
- [x] tracing av som standard
- [x] målrettede D1-indekser for dashboard/cash/valuta
- [x] R2 logical auditsnapshot kun søndag + månedsslutt
- [x] Workflow-state holder kompakte resultater; D1/R2 er autoritative lagre
- [x] produksjonsworkflow krever WAF cost guard før deploy

### D1/R2/deploy

- [x] D1-skjema har generator/paritetskontroll mot latest SQLite-reference
- [x] D1-migrasjoner etter baseline er additive/bakoverkompatible
- [x] R2 logical audit snapshot inkluderer broker estimates og consensus
- [x] produksjonsakseptanse tester statisk frontend, health, summary, history, economic NAV, FX-backtest og buyback forecast
- [x] FX-backtest må være `ready=true` med minst to klare historiske perioder
- [x] Worker rollback kjøres dersom post-deploy-akseptansen feiler
- [x] D1-migrasjoner rulles ikke tilbake av Worker rollback; Time Travel brukes ved database-restore

### CVM/minne

- [x] CVM ZIP holdes bounded
- [x] utpakket CVM CSV leses som stream fra ZIP-medlemmet
- [x] bare Bemobi-rader beholdes i Python-minne
- [x] CVM metadata kan ikke opprette/endre finansielle fakta automatisk

## Produksjon – gjenstår utenfor kodebasen

- [x] Workers Paid aktivert
- [ ] remote D1 opprettet
- [ ] R2 bucket opprettet
- [ ] validert produksjons-SQLite valgt/bygd med historiske OTEC-data
- [ ] streng produksjonspreflight passert
- [ ] produksjonsbootstrap SQL + manifest generert
- [ ] bootstrap importert til remote D1
- [ ] remote D1 eksakt avstemt mot manifest
- [ ] custom domain opprettet/tilknyttet
- [ ] WAF rate limiting for `/api/*` aktivert
- [ ] Budget Alerts og D1 billing notifications aktivert
- [ ] GitHub production secrets/variables konfigurert
- [ ] `CLOUDFLARE_WAF_COST_GUARD_READY=true` satt etter faktisk WAF-oppsett
- [ ] første manuelle deploy gjennomført
- [ ] full HTTP-akseptanse grønn
- [ ] fast Cron kontrollert i Workers Logs
- [ ] full Workflow kontrollert
- [ ] R2 råfiler/PDF/snapshot kontrollert etter retention-policy
- [ ] D1 Time Travel restore-drill gjennomført
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
7. bruk rapportert cash-FX til ny valuta-backtest/kalibrering;
8. rebuild CORE/FULL og økonomisk NAV;
9. kjør SQLite/D1 parity og produksjonspreflight på nytt.

## Regresjonsprinsipp

SQLite er fortsatt referanseimplementasjon. Cloudflare/D1 skal sammenlignes mot denne for finanslogikk og API-output. Nye investorjusteringer skal legges i økonomisk NAV-overlay eller eksplisitte nye modellversjoner – ikke skjult inn i validerte CORE/FULL-serier.
