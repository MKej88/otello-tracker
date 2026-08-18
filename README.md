# Otello NAV-oversikt

Privat investorverktøy for Otello Corporation ASA og Bemobi Mobile Tech. Løsningen beregner og viser løpende NAV, økonomisk investor-NAV, historisk NAV-rabatt, Bemobi-eksponering, tilbakekjøpsestimat, estimert valutafordeling av kontantbeholdningen og historisk kontroll av valutamodellen.

Produksjonsarkitekturen er laget for **Cloudflare Workers Paid** med React/Vite, Python Workers, D1, R2, Cron Triggers og Cloudflare Workflows.

## Status 18.08.2026

Kodebasen er gjennom **fase 15.7.2 – produksjonsherding**, med ytterligere herding av deploy, kostnadskontroll og produksjonsakseptanse.

**Kodebasen er klar for Cloudflare-cutover, men selve produksjonsmiljøet er ikke opprettet/deployet ennå.** Remote D1/R2, produksjonsdomene, WAF-regel og første produksjonsdeploy opprettes i go-live-prosedyren.

Det som er implementert nå:

- norsk React/Vite-dashboard via Workers Static Assets;
- Python Worker med FastAPI-kompatibelt API;
- D1 som autoritativ produksjonsdatabase;
- R2 for råkilder, NewsWeb-PDF-er og logiske revisjonssnapshots;
- 30-minutters rask oppdatering via Cron Trigger;
- daglig full oppdatering via Cloudflare Workflow;
- CORE NAV og FULL NAV;
- separat økonomisk NAV for investorformål;
- estimert NOK/USD/BRL-fordeling av kontantbeholdningen;
- historisk backtest av valutaeffekten;
- Bemobi-eksponering og markedsverdi;
- NewsWeb-basert tilbakekjøpshistorikk;
- Safe Harbour-basert tilbakekjøpsprognose;
- B3-, ECB-, CVM-, NewsWeb- og Euronext-integrasjoner;
- deterministisk SQLite → D1-bootstrap med manifest og hashes;
- eksakt avstemming av remote D1 før cutover;
- D1-basert writer-lock mellom rask og full oppdatering;
- produksjons-preflight mot manglende, gamle eller urene data;
- kostnadsvern for Workers Paid;
- full HTTP-akseptanse etter deploy;
- automatisk Worker-rollback dersom produksjonsakseptansen feiler.

## Hva som faktisk er synlig i frontend nå

Sidebaren viser følgende planlagte områder:

- Oversikt
- NAV
- Historikk
- Tilbakekjøp
- Bemobi
- Konsensus
- Aksjonærer
- Nyheter
- Innstillinger

**Bare `Oversikt` er aktiv som egen visning per i dag.** De øvrige knappene er bevisst deaktivert i frontend til egne sider/moduler bygges. Oversikt-siden inneholder allerede NAV, historikk, tilbakekjøp, Bemobi og modellstatus i samme dashboard.

## Arkitektur

```text
Nettleser
   |
   v
Cloudflare Worker + Workers Static Assets
   |
   |-- React/Vite frontend
   |-- Python Worker / FastAPI
   |       |
   |       +--> /api/*
   |
   +--> D1
   |    strukturert produksjonsdata
   |
   +--> R2
   |    råkilder, PDF-er og revisjonssnapshots
   |
   +--> Cron Trigger
   |    */30 * * * *
   |
   +--> Cloudflare Workflow
        35 3 * * *  (03:35 UTC)
```

`/api/*` sendes gjennom Worker-koden, mens statiske filer leveres direkte via Workers Static Assets. SPA-fallback er aktivert.

SQLite-backenden beholdes som deterministisk referanse-, test- og bootstrapmotor. Etter Cloudflare-cutover er **D1 produksjonsdatabasen**.

## Prosjektstruktur

```text
backend/       SQLite-referanse, modeller, import, bootstrap og tester
cloudflare/    Python Worker, D1-kode, Workflows, Cron, R2 og deployverktøy
frontend/      React/Vite-dashboard
docs/          modell-, sikkerhets- og go-live-dokumentasjon
data/          lokal runtime/bootstrap-data; produksjonsdata committes ikke
.github/       CI og Cloudflare-produksjonsdeploy
```

## API

Cloudflare-API-versjon: **0.12.0**.

```text
GET /api/health
GET /api/dashboard/summary
GET /api/dashboard/economic
GET /api/dashboard/fx-backtest
GET /api/dashboard/history
GET /api/buybacks/forecast
```

Historikk-endepunktet støtter blant annet:

```text
?days=365&max_points=300
```

Tilbakekjøpsprognosen støtter valgfri dato:

```text
?as_of_date=YYYY-MM-DD
```

## NAV-modellene

### CORE NAV

```text
Bemobi markedsverdi
+ modellert/rapportert kontantbeholdning
```

CORE NAV er den enkleste markedsbaserte verdimodellen.

### FULL NAV

```text
CORE NAV
+ øvrige nettoeiendeler/-forpliktelser (ONA)
```

Fra 15.09.2025 inkluderer ONA-modellen også behandling av Bemobi-fordringer og Otellos kontantoppgjorte opsjonsforpliktelse.

For opsjonsforpliktelsen brukes mark-to-market basert på OTEC-kurs og den validerte Black-Scholes-/innregningsmodellen. Regnskapsmessig CORE/FULL holdes separat fra investorjusteringene.

### Økonomisk NAV

Økonomisk NAV er et **separat investorlag**. Det erstatter ikke CORE eller FULL NAV.

Forenklet:

```text
Økonomisk NAV
= FULL NAV
+ dokumentert valutaendring på kontantbeholdningen
- ikke-innregnet økonomisk opsjonsoverheng
- estimerte driftskostnader siden siste rapporterte kontantanker
```

Modellen bruker kildebelagte økonomiske ankere fremfor skjulte konstanter i frontend.

For kontantbeholdning med dokumentert valutaeksponering revalueres USD- og BRL-komponentene med løpende valutakurser. Ufordelt residual behandles som estimert NOK i presentasjonsmodellen; ukjent valuta gjettes ikke.

Se `docs/economic-nav.md`.

## Valutamodell og backtest

Dashboardet viser et estimat på kontantbeholdningen fordelt på:

- NOK
- USD
- BRL

Fordelingen bygger på siste dokumenterte valutaeksponering og er tydelig merket som estimat.

Valuta-backtesten:

1. starter med rapportert valutaeksponering ved et historisk anker;
2. legger til kjente kontantstrømmer i opprinnelig valuta;
3. bruker historiske ECB-krysskurser;
4. beregner modellert valutaeffekt på kontantbeholdningen;
5. sammenligner mot rapportert faktisk valutaeffekt på cash;
6. bruker resultatført netto valutaresultat kun som diagnostisk kontroll.

Produksjonsdeploy krever at backtesten er `ready=true` og har minst **to klare historiske perioder**.

## Tilbakekjøpsmodellen

Tilbakekjøpsdelen kombinerer:

- NewsWeb-rapporterte tilbakekjøp;
- OTEC-handelsvolum;
- 20-dagers gjennomsnittsvolum;
- Safe Harbour-kapasitet;
- gjenværende programkapasitet;
- programmets prisgrense;
- historisk modelltreff.

Resultatet er et intervall og et baseestimat for neste handelsuke, med eksplisitt sikkerhetsnivå og eventuelle prisgrensevarsler.

Manglende OTEC-volumhistorikk er en hard produksjonsblokkering fordi prognosemotoren ellers ikke kan fungere som tenkt.

## Datakilder

### Otello

- rapporter og investorinformasjon for kontant-, balanse-, ONA- og opsjonsankre;
- NewsWeb for regulatoriske meldinger og tilbakekjøp;
- Euronext delayed-data for løpende OTEC-markedsdata og recovery;
- validert historikkfil ved første bootstrap.

### Bemobi

- B3 COTAHIST for offisiell BMOB3-sluttkurs;
- CVM for regulatoriske metadata og dokumentstatus.

CVM-metadata alene får ikke automatisk finansiell effekt i NAV-modellen.

### Valuta

- ECB for BRL/NOK og USD/NOK via krysskurser.

### Historiske bootstrapdata

Historiske OTEC-kurser skrapes ikke automatisk ved ren produksjonsbootstrap. De må komme fra:

1. validert Euronext-CSV; eller
2. den manuelle Investing.com-eksporten som fallback.

De store historikk-/bootstrapfilene ligger med vilje utenfor Git-repoet og er ignorert av `.gitignore`.

## Oppdateringsjobber

### Rask oppdatering – hvert 30. minutt

Cron:

```text
*/30 * * * *
```

Den raske banen håndterer blant annet:

- OTEC delayed/gap recovery;
- mulig OTEC EOD-finalisering;
- BMOB3 delayed/EOD;
- incremental NewsWeb;
- oppdatering av berørte cash-/ONA-/NAV-lag.

På børsfrie dager og utenfor relevante markedsvinduer unngås unødvendige nettverkskall der koden kan fastslå dette på forhånd.

### Full oppdatering – daglig

Workflow-plan:

```text
35 3 * * *
```

Full Workflow håndterer:

1. ECB-valuta;
2. B3 COTAHIST;
3. Bemobi/CVM;
4. NewsWeb-avstemming;
5. NewsWeb-PDF-er og tilbakekjøpsdetaljer;
6. OTEC recovery/EOD;
7. NAV-oppdatering;
8. D1 produksjons-preflight;
9. eventuell R2-snapshot;
10. ferdigstilling av jobb- og helsestatus.

## Writer-lock og samtidighet

Rask Cron og full Workflow bruker samme D1-baserte writer-lock i `runtime_state`.

Dette hindrer at begge skrivebanene oppdaterer markeds-/NAV-state samtidig. Låsen har utløp slik at et avbrudd ikke skal blokkere systemet permanent.

## Produksjons-preflight

Før en lokal referansedatabase kan eksporteres til produksjon kontrolleres blant annet:

- SQLite-integritet;
- korrekt migrasjonsnivå;
- nødvendige tabeller;
- ingen CI-/test-fixtures;
- rapporterte referanseankre;
- historisk OTEC- og BMOB3-dekning;
- historisk BRL/NOK og nødvendig USD/NOK;
- ferske OTEC/BMOB3/FX-data;
- NewsWeb-historikk;
- tilbakekjøpsdata;
- minst nødvendig OTEC-volumhistorikk;
- cash-, CORE NAV-, FULL NAV- og ONA-lag;
- dashboard `ready=true`;
- økonomisk NAV `ready=true` på samme dato som dashboardet.

Remote D1-preflight har også egen **produksjons-fixture-sentinel**, slik at test-/CI-rader blir en hard blokkering dersom de på noe tidspunkt havner i D1.

Valuta-backtesten kontrolleres i tillegg som en obligatorisk del av den endelige HTTP-akseptansen etter deploy.

## D1-bootstrap

Produksjonsbootstrapen lager en deterministisk pakke bestående av:

- SQL-importfil;
- manifest;
- radantall per tabell;
- logiske SHA-256-hashes;
- global logisk hash;
- nøkkeltall for sentrale finansielle tabeller.

Eksempel:

```bash
python cloudflare/tools/d1_bootstrap.py export \
  --database data/otello.db \
  --sql data/d1-bootstrap/otello-production.sql \
  --manifest data/d1-bootstrap/otello-production.manifest.json \
  --production \
  --date YYYY-MM-DD
```

`--production` nekter å skrive cutover-pakken hvis streng produksjons-preflight ikke passerer.

## Eksakt remote D1-avstemming

Etter import til Cloudflare D1 eksporteres remote-databasen read-only og sammenlignes med bootstrap-manifestet.

```bash
python cloudflare/tools/d1_bootstrap.py verify-remote \
  --database DB \
  --manifest data/d1-bootstrap/otello-production.manifest.json \
  --config cloudflare/wrangler.production.jsonc
```

Før første Worker-cutover skal avstemmingen være eksakt.

## R2

R2-binding:

```text
SOURCE_ARCHIVE
```

R2 brukes til:

- råkilder fra full oppdatering;
- relevante NewsWeb-PDF-er;
- logiske D1-revisjonssnapshots.

Det logiske D1-snapshotet tas **hver søndag og ved månedsslutt**. Den daglige Workflowen kaller snapshot-steget, men selve arkiveringen hopper kontrollert over på andre dager.

Snapshotet er chunket, gzip-komprimert, innholdsadressert og har SHA-256-manifest.

Blant tabellene som inngår er:

- markedspriser og valuta;
- holdings;
- kontantankre og kontantbevegelser;
- ONA;
- tilbakekjøp;
- aksjetall;
- NAV-snapshots;
- meglerestimater;
- konsensus;
- provenance.

`company_news`, `market_activity` og `runtime_state` er bevisst utelatt fordi de er høyfrekvente eller rekonstruerbare.

D1 Time Travel er primær mekanisme for kortsiktig full databasegjenoppretting. R2-snapshotet er et separat revisjons-/langtidslag.

## Workers Paid og kostnadskontroll

Produksjonskonfigurasjonen settes med bevisst lavere grenser enn plattformens maksimale kapasitet:

```text
CPU:          60 000 ms
Subrequests:  500
```

I tillegg brukes:

- Workers Caching på API-entrypointen;
- direkte Static Assets for frontend;
- 5 % sampling av invocation logs;
- tracing avslått som standard;
- målrettede D1-indekser;
- writer-lock mot doble skrivejobber;
- WAF rate limiting på `/api/*` som krav før produksjonsdeploy;
- budsjett- og D1-forbruksvarsler som del av go-live-runbooken.

Se `docs/cloudflare-paid-cost-guard.md`.

## Sikkerhet

Frontend leveres med blant annet:

- Content Security Policy;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- deaktivert kamera, mikrofon og geolokasjon via Permissions Policy.

API-responsene får tilsvarende sikkerhetsheaders fra Worker-koden.

FastAPI-dokumentasjon og OpenAPI-endepunkt er deaktivert i produksjons-API-et.

## Produksjonsdeploy

GitHub Action:

```text
.github/workflows/deploy-cloudflare.yml
```

Produksjonsdeploy krever:

- `CLOUDFLARE_API_TOKEN`;
- `CLOUDFLARE_ACCOUNT_ID`;
- `CLOUDFLARE_D1_DATABASE_ID`;
- Worker-navn;
- D1-navn;
- R2-bucket;
- custom domain;
- samsvarende HTTPS `CLOUDFLARE_PUBLIC_URL`;
- `CLOUDFLARE_WAF_COST_GUARD_READY=true`.

Workflowen:

1. validerer produksjonsinnstillingene;
2. bygger frontend;
3. installerer pinnede Worker-/Wrangler-verktøy;
4. renderer produksjonskonfigurasjon;
5. kjører remote D1-migreringer;
6. deployer Python Worker og Workflow;
7. kjører obligatorisk HTTP-akseptanse;
8. ruller Worker tilbake hvis en kontroll etter deploy feiler.

## HTTP-akseptanse etter deploy

Den faktiske produksjonssiden testes – ikke bare deploykommandoen.

Følgende kontrolleres:

```text
/
/api/health
/api/dashboard/summary
/api/dashboard/history
/api/dashboard/economic
/api/dashboard/fx-backtest
/api/buybacks/forecast
```

Akseptansen krever blant annet:

- riktig sidetittel;
- CSP og sikkerhetsheaders;
- `environment=cloudflare`;
- dashboard `ready=true`;
- historikk med datapunkter;
- økonomisk NAV klar;
- samme dato for økonomisk NAV og hoveddashboard;
- konsistent økonomisk/konservativ NAV;
- valuta-backtest klar med minst to perioder;
- tilbakekjøpsmotor uten `INSUFFICIENT_VOLUME_HISTORY`;
- modelldato maksimalt sju dager gammel.

Hvis Worker-deploy er gjennomført, men HTTP-akseptansen feiler, forsøker GitHub Action automatisk å rulle Worker tilbake til forrige deployerte versjon.

**D1-migreringer rulles ikke tilbake av Worker-rollback.** Produksjonsmigreringer skal derfor være additive og bakoverkompatible. D1 Time Travel brukes ved behov for databasegjenoppretting.

## Cloudflare go-live

Selve go-live gjennomføres kontrollert og manuelt første gang.

Hovedrekkefølge:

1. opprett remote D1;
2. opprett R2-bucket;
3. bygg/oppdater validert lokal produksjonsdatabase;
4. kjør streng preflight;
5. lag D1-bootstrap og manifest;
6. importer til remote D1;
7. kjør foreign-key-kontroll;
8. kjør `verify-remote`;
9. sett custom domain;
10. sett WAF rate limiting;
11. opprett budsjett-/D1-varsler;
12. legg inn GitHub production secrets/variables;
13. kjør første manuelle deploy;
14. kontroller HTTP-akseptansen;
15. kontroller minst én rask Cron-kjøring;
16. kontroller minst én full Workflow;
17. kontroller R2-arkivering;
18. gjør en kontrollert D1 Time Travel-restoreøvelse;
19. aktiver automatisk deploy med `CLOUDFLARE_DEPLOY_ENABLED=true`.

Detaljert prosedyre: `docs/cloudflare-go-live.md`.

## Lokal utvikling

Den lokale SQLite-backenden er fortsatt nyttig til:

- modellutvikling;
- historiske rebuilds;
- bootstrap;
- regresjonstester;
- sammenligning mot Cloudflare/D1-implementasjonen.

Frontend bygges med Node 22:

```bash
cd frontend
npm ci
npm run build
```

Cloudflare-produksjonskonfigurasjonen genereres fra basisfilen og lagres i en gitignored `wrangler.production.jsonc`.

## Viktige dokumenter

- `docs/cloudflare-go-live.md` – full produksjonsrunbook
- `docs/cloudflare-paid-cost-guard.md` – kostnadsvern og WAF
- `docs/economic-nav.md` – økonomisk NAV
- `cloudflare/README.md` – Cloudflare-implementasjonen

## Neste finansielle kontrollpunkt

Neste planlagte rapportanker er Otello 1H26 den **21.08.2026**. Når rapporten publiseres skal nye rapporterte kontant-/balanseankre, ONA, opsjonsforpliktelse/-forutsetninger og driftskostnader avstemmes før de eventuelt blir nye kildebelagte modellankre.

Kontantfordeling per valuta oppdateres bare dersom ny rapport faktisk dokumenterer den. Modellen skal ikke gjette ukjent valutafordeling.
