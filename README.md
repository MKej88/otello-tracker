# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med løpende NAV, økonomisk investor-NAV, historisk NAV-rabatt, tilbakekjøp, Bemobi-eksponering og eksplisitt datakvalitet.

## Status 18.08.2026

Kodebasen er ferdig gjennom **Phase 15.7.2 – final production hardening**. Cloudflare-implementasjonen er CI-/regresjonsmålet; faktisk remote D1/R2 og første produksjonsdeploy gjøres først i go-live-prosedyren.

Det betyr at repository-siden nå inneholder:

- React/Vite-dashboard på Workers Static Assets;
- Python Worker/FastAPI API mot D1;
- 30-minutters bounded fast refresh;
- daglig full refresh i Cloudflare Workflow;
- R2-kildearkiv og logisk revisjonssnapshot;
- deterministisk SQLite → D1 bootstrap med manifest/hashes;
- remote D1 manifestavstemming etter cutover;
- CORE NAV, FULL NAV og separat økonomisk NAV;
- NewsWeb/CVM/B3/ECB/Euronext-integrasjoner;
- Safe Harbour-basert tilbakekjøpsprognose;
- preflight som også krever fungerende økonomisk NAV og nødvendig OTEC-volumhistorikk;
- koordinert writer-lock mellom fast Cron og full Workflow;
- produksjonsakseptanse og automatisk Worker-rollback dersom en post-deploy-kontroll feiler.

## Arkitektur

```text
Browser
  |
  v
Cloudflare Python Worker + Static Assets
  |-- FastAPI /api/*
  |-- React/Vite
  |
  +--> D1             strukturert produksjonsdata
  +--> R2             PDF/råkilder/auditsnapshot
  +--> Cron           */30 * * * *
  +--> Workflow       03:35 UTC daglig fullrefresh
  +--> runtime_state  writer-lock og lette driftsmarkører
```

SQLite-backenden beholdes som deterministisk referanse/regresjonsmotor og bootstrap-kilde. Den er ikke produksjonsdatabasen etter Cloudflare-cutover.

## API

```text
GET /api/health
GET /api/dashboard/summary
GET /api/dashboard/economic
GET /api/dashboard/history
GET /api/buybacks/forecast
```

## NAV-modeller

### CORE NAV

```text
Bemobi markedsverdi + modellert/rapportert cash
```

### FULL NAV

```text
CORE NAV + øvrige nettoeiendeler/-forpliktelser (ONA)
```

Fra 15.09.2025:

```text
ONA = base ONA ex option
    + Bemobi distribution receivables
    - Otello cash-settled option liability
```

Opsjonsforpliktelsen mark-to-marketes med OTEC og den validerte Black-Scholes-/recognition-modellen. Recognition-faktoren holdes mot siste rapporterte evidens; CORE/FULL-formlene er ikke endret i Phase 15.7.2.

### Økonomisk NAV

Økonomisk NAV er et separat investor-overlay og endrer ikke CORE/FULL:

```text
Økonomisk NAV
= FULL NAV
+ dokumentert valutaendring på cash
- ikke-innregnet økonomisk opsjonsoverheng
- estimerte driftskostnader siden siste rapporterte cash-anker
```

Driftskostnadsforutsetningene er nå kildebelagte, kuraterte data med provenance – ikke Python-konstanter. For 31.12.2025-ankeret revalueres bare eksplisitt dokumentert USD- og BRL-cash. Resten er merket `UNALLOCATED` og holdes på ankerverdi i stedet for å gjette valuta.

Se `docs/economic-nav.md`.

## Datakilder

- **Otello IR:** rapporterte cash-/balanse-/opsjonsankre og økonomiske modellankre
- **B3:** BMOB3 COTAHIST / delayed
- **ECB:** BRL/NOK og USD/NOK
- **Euronext:** OTEC delayed/historikk og handelsaktivitet
- **NewsWeb:** Otello-meldinger, tilbakekjøp og transaksjons-PDF-er
- **CVM:** Bemobi regulatoriske metadata; ingen automatisk finansiell effekt fra metadata alene
- **Investing.com CSV:** kun manuell historisk OTEC-fallback

## Produksjonskontroller

Før en database kan brukes til cutover krever preflight blant annet:

- ingen CI/test-fixtures;
- historisk og fersk OTEC/BMOB3/FX-dekning;
- NewsWeb-historikk og tilbakekjøpsfakta;
- minst nødvendig OTEC-volumhistorikk for tilbakekjøpsmotoren;
- ferske cash/CORE/FULL/ONA-lag;
- dashboard `ready=true`;
- økonomisk NAV `ready=true` på samme dato;
- buyback-motoren må ikke være deaktivert av manglende volumhistorikk.

Ren bootstrap seeder den kuraterte OTEC-volumhistorikken automatisk.

## D1-bootstrap og avstemming

Produksjonsbootstrap lager:

- SQL-importfil;
- radantall og SHA-256 per eksportert tabell;
- global logisk hash;
- nøkkeltall for NAV, markedsdata, FX, cash, holdings og buybacks.

Etter remote import skal databasen eksporteres read-only og avstemmes eksakt mot samme manifest med:

```bash
python cloudflare/tools/d1_bootstrap.py verify-remote \
  --database DB \
  --manifest data/d1-bootstrap/otello-production.manifest.json \
  --config cloudflare/wrangler.production.jsonc
```

## Scheduling og samtidighet

- fast refresh: `*/30 * * * *`
- full Workflow: `35 3 * * *`

Begge skrivebaner bruker én D1-basert advisory writer-lock med utløp. Dermed kan de ikke skrive markeds-/NAV-state samtidig selv dersom en Workflow varer inn i neste halvtimeskjøring.

## R2

Det daglige logiske auditsnapshotet dekker finans-/modellstate, inkludert broker estimates og consensus. Høyfrekvente/re-konstruerbare driftstabeller som `company_news`, `market_activity` og `runtime_state` er bevisst utelatt. D1 Time Travel er fortsatt mekanismen for full databasegjenoppretting.

## Deploy

Produksjonsworkflowen bygger frontend, renderer konfigurasjon, migrerer D1 og deployer Worker/Workflow. Med offentlig URL satt testes health, summary, economic NAV og buyback forecast. Hvis en kontroll etter Worker-deploy feiler, rulles Worker tilbake til forrige deployerte versjon.

D1-migreringer rulles ikke tilbake av Worker-rollback. Nye produksjonsmigreringer skal derfor fortsatt være additive/bakoverkompatible, og Time Travel brukes ved behov for D1-restore.

## Det som fortsatt gjenstår utenfor kodebasen

Faktisk go-live krever fortsatt:

1. validert produksjons-SQLite eller ny ren bootstrap;
2. Cloudflare Workers Paid;
3. remote D1 og R2;
4. GitHub production secrets/variables;
5. produksjonsbootstrap + eksakt remote manifestavstemming;
6. første manuelle deploy med HTTP-akseptanse;
7. kontroll av Workers Logs, Workflow og R2;
8. trygg D1 Time Travel restore-drill;
9. eventuelt custom domain;
10. først deretter `CLOUDFLARE_DEPLOY_ENABLED=true`.

Se `docs/cloudflare-go-live.md`.

## Neste finansielle kontrollpunkt

Otello 1H26 er planlagt 21.08.2026. Når rapporten publiseres skal nye rapporterte cash-/balanseankre, ONA, opsjonsforpliktelse/-forutsetninger og underliggende driftskostnader avstemmes før de blir nye kildebelagte modellankre.
