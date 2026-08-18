# Otello NAV-oversikt

Privat investeringsdashboard for Otello/Bemobi med løpende NAV, økonomisk investor-NAV, historisk NAV-rabatt, tilbakekjøp, Bemobi-eksponering, valutaestimat/backtest og eksplisitt datakvalitet.

## Status 18.08.2026

Kodebasen er ferdig gjennom **Phase 15.7.2 – final production hardening**, med påfølgende Workers Paid-, kostnads- og produksjonsakseptanse-herding. Cloudflare Workers Paid er aktivert på kontoen. Faktiske remote D1/R2-ressurser og første produksjonsdeploy gjøres i go-live-prosedyren.

Repository-siden inneholder nå:

- React/Vite-dashboard på Workers Static Assets;
- Python Worker/FastAPI API mot D1;
- 30-minutters bounded fast refresh;
- daglig full refresh i Cloudflare Workflow;
- R2-kildearkiv og ukentlig/månedsslutt logisk revisjonssnapshot;
- deterministisk SQLite → D1 bootstrap med manifest/hashes;
- remote D1 manifestavstemming etter cutover;
- CORE NAV, FULL NAV og separat økonomisk NAV;
- estimert NOK/USD/BRL-fordeling av cash og historisk valuta-backtest;
- NewsWeb/CVM/B3/ECB/Euronext-integrasjoner;
- Safe Harbour-basert tilbakekjøpsprognose;
- preflight som krever fungerende økonomisk NAV, historisk valuta-backtest og nødvendig OTEC-volumhistorikk;
- koordinert writer-lock mellom fast Cron og full Workflow;
- Workers Paid-kostnadssperrer, API-cache og D1-ytelsesindekser;
- obligatorisk produksjonsakseptanse og automatisk Worker-rollback dersom en kontroll etter deploy feiler.

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
GET /api/dashboard/fx-backtest
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

Opsjonsforpliktelsen mark-to-marketes med OTEC og den validerte Black-Scholes-/recognition-modellen. Recognition-faktoren holdes mot siste rapporterte evidens; CORE/FULL-formlene er ikke endret av investor-overlayene.

### Økonomisk NAV

Økonomisk NAV er et separat investor-overlay og endrer ikke CORE/FULL:

```text
Økonomisk NAV
= FULL NAV
+ dokumentert valutaendring på cash
- ikke-innregnet økonomisk opsjonsoverheng
- estimerte driftskostnader siden siste rapporterte cash-anker
```

Driftskostnadsforutsetningene er kildebelagte, kuraterte data med provenance – ikke Python-konstanter. For 31.12.2025-ankeret revalueres eksplisitt dokumentert USD- og BRL-cash. Den rapporterte residualen behandles separat og brukes som estimert NOK i presentasjonsmodellen uten å endre den konservative NAV-logikken.

Valuta-backtesten bruker rapportert valutaeffekt på kontantbeholdningen som primær fasit og resultatført valutaresultat som diagnostisk kontroll.

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

Ren bootstrap seeder den kuraterte OTEC-volumhistorikken automatisk. Historiske OTEC-kurser må komme fra validert Euronext-CSV eller den manuelle Investing.com-filen; de skrapes ikke automatisk.

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

Rå kildefiler og relevante NewsWeb-PDF-er arkiveres content-addressed. Det separate logiske D1-auditsnapshotet tas **hver søndag og ved månedsslutt**, ikke daglig. Det dekker finans-/modellstate, inkludert broker estimates og consensus. Høyfrekvente/re-konstruerbare driftstabeller som `company_news`, `market_activity` og `runtime_state` er bevisst utelatt. D1 Time Travel er mekanismen for full korttids-gjenoppretting.

## Workers Paid og kostnadskontroll

Produksjonskonfigurasjonen bruker Workers Paid-kapasitet uten å åpne plattformens maksimumsgrenser:

- 60 000 ms CPU per invocation;
- 500 subrequests per invocation;
- Workers Caching kun på API-entrypointen;
- statiske assets går direkte via Workers Static Assets;
- 5 % loggsampling;
- tracing av som standard;
- målrettede D1-indekser;
- WAF rate limiting på `/api/*` kreves før produksjonsdeploy.

Se `docs/cloudflare-paid-cost-guard.md`.

## Deploy

Produksjonsworkflowen bygger frontend, renderer konfigurasjon, migrerer D1 og deployer Worker/Workflow. Produksjonsdeploy krever eget HTTPS-domene, samsvarende `CLOUDFLARE_PUBLIC_URL` og aktiv WAF-kostnadssperre.

Etter deploy testes den faktiske frontend-siden og alle brukerrelevante API-er: health, summary, historikk, economic NAV, valuta-backtest og buyback forecast. Valuta-backtesten må være klar med minst to perioder. Hvis en kontroll etter Worker-deploy feiler, rulles Worker tilbake til forrige deployerte versjon.

D1-migreringer rulles ikke tilbake av Worker-rollback. Nye produksjonsmigreringer skal derfor være additive/bakoverkompatible, og Time Travel brukes ved behov for D1-restore.

## Det som fortsatt gjenstår utenfor kodebasen

Faktisk go-live krever fortsatt:

1. opprette remote D1 og R2;
2. bygge/velge validert produksjons-SQLite med historiske OTEC-data;
3. kjøre streng produksjonspreflight og lage bootstrap-pakken;
4. importere bootstrap til remote D1;
5. kjøre eksakt `verify-remote` mot manifestet;
6. konfigurere GitHub production secrets/variables;
7. sette custom domain, WAF rate limiting og budsjett-/D1-varsler;
8. kjøre første manuelle deploy med full HTTP-akseptanse;
9. kontrollere Workers Logs, fast Cron, Workflow og R2;
10. gjøre en trygg D1 Time Travel restore-drill;
11. først deretter sette `CLOUDFLARE_DEPLOY_ENABLED=true`.

Se `docs/cloudflare-go-live.md`.

## Neste finansielle kontrollpunkt

Otello 1H26 er planlagt 21.08.2026. Når rapporten publiseres skal nye rapporterte cash-/balanseankre, ONA, opsjonsforpliktelse/-forutsetninger og underliggende driftskostnader avstemmes før de blir nye kildebelagte modellankre.
