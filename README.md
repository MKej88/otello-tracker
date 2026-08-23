# Otello NAV-oversikt

Privat investorverktøy for **Otello Corporation ASA** og **Bemobi Mobile Tech**. Løsningen beregner og viser løpende NAV, økonomisk investor-NAV, historisk NAV-rabatt, Bemobi-eksponering, tilbakekjøpsestimat, kontant-/valutaeffekter og konsensus.

Produksjonen kjører på **Cloudflare Workers Paid** med React/Vite, Python Workers, D1, R2, Cron Triggers og Cloudflare Workflows.

## Status 23.08.2026

Produksjonen er live og deploy-/diagnosekjeden er etablert.

- D1 er autoritativ produksjonsdatabase.
- R2 brukes til råkilder, NewsWeb-PDF-er og logiske revisjonssnapshots.
- rask Cron kjører hvert 30. minutt;
- daglig Full Workflow kjører kl. 03:35 UTC;
- rask og full oppdatering bruker felles D1-basert writer-lock, og hver Full Workflow-instans har unik lock-identitet;
- D1 Time Travel er primær database-recovery;
- automatisk deploy fra grønn `main`-CI har production-shaped kontroll før remote D1, produksjonsakseptanse og Worker-rollback;
- daglig skrivebeskyttet GitHub-diagnostikk leser Cloudflare Workflow- og D1-status etter nattkjøringen;
- Workers Paid-kostnadsvern, WAF og begrenset observability er konfigurert.

Historiske go-live-, Docker-produksjons- og migreringsplaner er fjernet fra aktiv dokumentasjon. Dagens arkitektur og drift beskrives i `docs/architecture.md` og `docs/runbook.md`.

## Frontend

Aktive visninger:

- Oversikt
- NAV
- Historikk
- Tilbakekjøp
- Bemobi
- Konsensus

Nyheter og Innstillinger er fortsatt inaktive områder i navigasjonen.

## Arkitektur

```text
Nettleser
   |
   v
Cloudflare Worker + Workers Static Assets
   |
   |-- React/Vite frontend
   |-- Python Worker API (/api/*)
   |
   +--> D1
   |    autoritativ produksjonsdatabase
   |
   +--> R2
   |    råkilder, PDF-er og revisjonssnapshots
   |
   +--> Cron Trigger
   |    */30 * * * *
   |
   +--> Cloudflare Workflow
        35 3 * * * UTC
```

SQLite/Docker-implementasjonen under `backend/` beholdes som deterministisk referanse-, test- og regresjonsmotor. Den er ikke produksjonsdatabasen.

Se `docs/architecture.md`.

## Sentrale API-endepunkter

Cloudflare-/referanse-API-versjon: **0.13.0**.

```text
GET /api/health
GET /api/market/quotes
GET /api/dashboard/summary
GET /api/dashboard/economic
GET /api/dashboard/waterfall
GET /api/dashboard/fx-backtest
GET /api/dashboard/history
GET /api/dashboard/discount-history
GET /api/dashboard/report-status
GET /api/dashboard/runtime-status
GET /api/buybacks/forecast
GET /api/buybacks/dashboard
GET /api/bemobi/dashboard
GET /api/bemobi/consensus
GET /api/bemobi/source-status
```

Aktive frontend-API-er inngår i Worker-smoke og/eller produksjonsakseptanse. `runtime-status` inngår i produksjonsakseptansen og viser kun kompakt, sanitert driftstatus; detaljerte feil beholdes i den private GitHub-diagnostikken.

## NAV-modellene

### CORE NAV

```text
Bemobi markedsverdi
+ modellert/rapportert kontantbeholdning
```

### FULL NAV

```text
CORE NAV
+ øvrige nettoeiendeler/-forpliktelser (ONA)
```

FULL NAV inkluderer den validerte behandlingen av Bemobi-fordringer og Otellos kontantoppgjorte opsjonsforpliktelse.

### Økonomisk NAV

Økonomisk NAV er et separat investorlag og erstatter ikke CORE/FULL.

Forenklet:

```text
Økonomisk NAV
= FULL NAV
+ dokumentert valutaendring på kontantbeholdningen
- ikke-innregnet økonomisk opsjonsoverheng
- estimerte driftskostnader siden siste rapporterte kontantanker
```

Se `docs/economic-nav.md` og `docs/option-liability.md`.

## Datakilder

### Otello

- selskapets rapporter og investorinformasjon for cash-, balanse-, ONA- og opsjonsankre;
- NewsWeb for regulatoriske meldinger og tilbakekjøp;
- Euronext delayed-data for løpende OTEC-markedsdata og recovery.

### Bemobi

- B3 COTAHIST for offisiell BMOB3-sluttkurs;
- CVM for regulatoriske metadata og dokumentstatus;
- Bemobi IR for eierandel og offentlig analytikerdekning;
- offentlige MarketScreener-/XP-data der de kan verifiseres og spores.

CVM-metadata alene skal ikke opprette eller endre finansielle fakta.

### Valuta

- Norges Bank er primærkilde for **direkte BRL/NOK og USD/NOK**. Det brukes ikke lenger EUR-kryss i den løpende produksjonsoppdateringen.
- Historiske ECB-rader beholdes kun som kildeproveniens/fallback; nye valutadata hentes ikke fra ECB.

## Oppdateringsjobber

### Rask oppdatering

```text
*/30 * * * *
```

Den raske banen håndterer lette og inkrementelle oppdateringer som OTEC/BMOB3, NewsWeb og berørte cash-/NAV-lag.

### Full oppdatering

```text
35 3 * * * UTC
```

Full Workflow håndterer tyngre kilder og avstemming, blant annet Norges Bank, Life360, B3, CVM, Bemobi-webkilder, NewsWeb, OTEC recovery/EOD, NAV, produksjonspreflight og R2-snapshot ved behov.

Begge write-paths bruker samme writer-lock. Full Workflow bruker unik per-instans-identitet, locken fornyes gjennom kjøringen, cleanup skal frigjøre låsen også ved feil, og expiry er siste sikkerhetsnett. En startet D1-jobb terminaliseres eksplisitt til `FAILED` ved hard Workflow-feil dersom den fortsatt står `RUNNING`.

## Nattdiagnostikk

GitHub Actions kjører daglig skrivebeskyttet diagnostikk etter nattens Full Workflow. Diagnostikken bruker et separat Cloudflare-token med lesetilgang og kontrollerer blant annet:

- status, trinn, retries og feil for siste Cloudflare Workflow-instans;
- siste full- og 30-minuttersjobb i D1 og om de er ferske;
- Norges Bank BRL/NOK og USD/NOK mot forventet Oslo Børs-handelsdag;
- siste CORE-NAV og valuta-datoen som NAV faktisk bruker;
- siste kildehelse.

Den planlagte diagnosejobben feiler dersom den finner et reelt Workflow- eller D1-avvik. Diagnostikken endrer ikke produksjonsdata og trigger ikke Cloudflare Workflows.

## Deploy og produksjonskontroll

`main` beskyttes av pull request og obligatorisk CI.

```text
PR
 -> CI grønn
 -> merge til main
 -> CI på main grønn
 -> production gate
 -> verifiser eksakt testet SHA
 -> render/valider produksjonskonfig
 -> production-shaped Worker dry-run + runtime-kontroll
 -> remote D1-migreringer
 -> deploy av eksakt testet SHA
 -> produksjons-HTTP-akseptanse
 -> Worker-rollback ved feil
```

Remote D1 berøres ikke før den renderte produksjonskonfigurasjonen og Worker-bundlen for eksakt deploy-SHA er kontrollert. Produksjonsakseptansen tester frontend, health, NAV, økonomisk NAV, historikk, runtime-status, tilbakekjøp, Bemobi, konsensus og øvrige aktive investorendepunkter.

Worker-rollback reverserer ikke D1-migreringer. Nye migreringer skal derfor være additive og bakoverkompatible.

## D1 og recovery

D1 Time Travel er primær mekanisme for full databasegjenoppretting.

R2 logical snapshot er et ekstra revisjons-/recoverylag og tas søndag og ved månedsslutt. Snapshotene er chunket og verifiseres med manifest/SHA-256.

Den gamle engangs-workflowen som bootstrappet produksjons-D1 er fjernet. `cloudflare/tools/d1_bootstrap.py` beholdes som deterministisk referanse-/recoveryverktøy.

Migreringsnumre som tidligere har vært brukt skal ikke gjenbrukes. Se `docs/migration-history.md`.

## Workers Paid og kostnadskontroll

Produksjonskonfigurasjonen bruker bevisst avgrensede grenser:

```text
CPU:          60 000 ms
Subrequests:  50 000
```

I tillegg brukes blant annet API-cache, direkte Static Assets, begrenset loggsampling, tracing av som standard, målrettede D1-indekser, writer-lock, WAF rate limiting og Budget Alerts.

Se `docs/cloudflare-paid-cost-guard.md`.

## Sikkerhet

Frontend leveres med blant annet CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` og Permissions Policy. Produksjonscredentials skal ligge i GitHub/Cloudflare secrets og variables, aldri i Git.

Produksjonsdeploy og skrivebeskyttet diagnostikk bruker separate Cloudflare-token med ulike rettigheter. Se `docs/cloudflare-api-token.md`.

## Lokal utvikling

SQLite-backenden brukes fortsatt til modellutvikling, historiske rebuilds, regresjonstester og sammenligning mot Cloudflare/D1.

Frontend:

```bash
cd frontend
npm ci
npm run build
```

`.env.example` gjelder kun lokal Docker/SQLite-referanse. Produksjonskonfigurasjonen genereres separat fra Cloudflare-basisoppsettet.

## Viktige dokumenter

- `docs/architecture.md` – dagens produksjonsarkitektur
- `docs/runbook.md` – drift, feil og recovery
- `docs/migration-history.md` – reserverte migreringsnumre og regler
- `docs/economic-nav.md` – økonomisk NAV
- `docs/option-liability.md` – opsjonsmodellen
- `docs/buyback-forecast.md` – tilbakekjøpsmodellen
- `docs/cloudflare-paid-cost-guard.md` – kostnadsvern
- `docs/cloudflare-api-token.md` – deploy- og read-only diagnose-token
- `docs/ci-auto-deploy.md` – automatisk produksjonsdeploy
- `cloudflare/README.md` – Cloudflare-implementasjonen
- `ROADMAP.md` – neste finansielle og tekniske prioriteringer

## Neste kontrollpunkt

Neste finansielle hovedkontroll er Otello 1H26. Arbeidsrekkefølgen ved ny rapport ligger i `ROADMAP.md` og `docs/runbook.md`.
