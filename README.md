# Otello NAV-oversikt

Privat investorverktøy for **Otello Corporation ASA** og **Bemobi Mobile Tech**. Løsningen beregner og viser løpende NAV, økonomisk investor-NAV, historisk NAV-rabatt, Bemobi-eksponering, tilbakekjøpsestimat, kontant-/valutaeffekter og historisk kontroll av valutamodellen.

Produksjonen kjører på **Cloudflare Workers Paid** med React/Vite, Python Workers, D1, R2, Cron Triggers og Cloudflare Workflows.

## Status 19.08.2026

**Produksjons-go-live er ferdig og verifisert.**

Følgende er kontrollert i faktisk produksjon:

- Cloudflare Worker og frontend er deployet på custom domain med HTTPS;
- D1 er autoritativ produksjonsdatabase;
- R2 brukes til råkilder, NewsWeb-PDF-er og logiske D1-snapshots;
- rask Cron kjører hvert 30. minutt;
- daglig Full Workflow fungerer;
- writer-lock mellom rask og full oppdatering er testet ende-til-ende;
- R2 logical snapshot er verifisert i produksjon;
- D1 Time Travel restore-drill er gjennomført mot separat drill-database;
- WAF cost guard på `/api/*` er aktiv;
- Budget Alerts på USD 1 og USD 5 er opprettet;
- Workers-metrics er kontrollert uten feil på aktiv deployment;
- produksjons-HTTP-akseptanse er grønn;
- automatisk Worker-rollback er konfigurert dersom akseptansen etter deploy feiler.

### Automatisk produksjonsdeploy

`main` er beskyttet av rulesetet **Protect main**. Endringer går via pull request og obligatoriske CI-checks.

Produksjonsflyten er:

```text
PR
  -> CI grønn
  -> merge til main
  -> CI på main grønn
  -> production environment-gate
  -> automatisk Cloudflare-deploy av eksakt testet SHA
  -> produksjons-HTTP-akseptanse
  -> rollback av Worker ved feil etter deploy
```

`CLOUDFLARE_DEPLOY_ENABLED=true` er aktivert og kjeden er testet ende-til-ende i produksjon.

Obligatoriske CI-jobber omfatter:

- Backend reference tests
- Frontend build
- Cloudflare D1 schema + historical data parity
- Cloudflare Python Worker API
- Docker regression reference

## Hva som er synlig i frontend nå

Sidebaren viser planlagte områder for:

- Oversikt
- NAV
- Historikk
- Tilbakekjøp
- Bemobi
- Konsensus
- Aksjonærer
- Nyheter
- Innstillinger

**Bare `Oversikt` er aktiv som egen visning foreløpig.** De øvrige knappene er bevisst deaktivert til egne sider/moduler bygges. Oversikt-siden inneholder allerede NAV, historikk, tilbakekjøp, Bemobi og modellstatus.

## Arkitektur

```text
Nettleser
   |
   v
Cloudflare Worker + Workers Static Assets
   |
   |-- React/Vite frontend
   |-- Python Worker / FastAPI-kompatibelt API
   |       |
   |       +--> /api/*
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
        35 3 * * *  (UTC)
```

`/api/*` går gjennom Worker-koden. Statiske frontend-filer leveres via Workers Static Assets. SQLite-backenden beholdes som deterministisk referanse-, test- og bootstrapmotor.

## Prosjektstruktur

```text
backend/       SQLite-referanse, modeller, import, bootstrap og tester
cloudflare/    Python Worker, D1-kode, Workflows, Cron, R2 og deployverktøy
frontend/      React/Vite-dashboard
docs/          modell-, sikkerhets- og go-live-dokumentasjon
data/          lokal runtime/bootstrap-data; produksjonsdata committes ikke
.github/       CI, branch-gates og Cloudflare-produksjonsdeploy
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

Historikk:

```text
/api/dashboard/history?days=365&max_points=300
```

Tilbakekjøpsprognose med valgfri dato:

```text
/api/buybacks/forecast?as_of_date=YYYY-MM-DD
```

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

Fra 15.09.2025 inkluderer ONA-modellen også behandling av Bemobi-fordringer og Otellos kontantoppgjorte opsjonsforpliktelse.

Opsjonsforpliktelsen mark-to-market-beregnes med OTEC-kurs og den validerte Black-Scholes-/innregningsmodellen. Regnskapsmessig CORE/FULL holdes separat fra investorjusteringene.

### Økonomisk NAV

Økonomisk NAV er et separat investorlag og erstatter ikke CORE eller FULL NAV.

Forenklet:

```text
Økonomisk NAV
= FULL NAV
+ dokumentert valutaendring på kontantbeholdningen
- ikke-innregnet økonomisk opsjonsoverheng
- estimerte driftskostnader siden siste rapporterte kontantanker
```

Dokumenterte USD- og BRL-komponenter i kontantbeholdningen revalueres med løpende valutakurser. Residual som ikke er tilstrekkelig dokumentert på valuta holdes foreløpig som **`UNALLOCATED`** med fast ankerverdi; modellen skal ikke gjette ukjent valutaeksponering.

Se `docs/economic-nav.md`.

## Valutamodell og backtest

Valutamodellen bruker dokumenterte cash-/valutaankre og historiske ECB-krysskurser. Backtesten:

1. starter med rapportert valutaeksponering ved et historisk anker;
2. legger til kjente kontantstrømmer i opprinnelig valuta;
3. bruker historiske ECB-krysskurser;
4. beregner modellert valutaeffekt;
5. sammenligner mot rapportert faktisk valutaeffekt på cash;
6. bruker resultatført netto valutaresultat kun som diagnostisk kontroll.

Produksjonsakseptansen krever at backtesten er `ready=true` med minst **to klare historiske perioder**.

## Tilbakekjøpsmodellen

Tilbakekjøpsdelen kombinerer:

- NewsWeb-rapporterte tilbakekjøp;
- OTEC-handelsvolum;
- 20-dagers gjennomsnittsvolum;
- Safe Harbour-kapasitet;
- gjenværende programkapasitet;
- programmets prisgrense;
- historisk modelltreff.

Resultatet er intervall og baseestimat for neste handelsuke med sikkerhetsnivå og eventuelle prisgrensevarsler.

Manglende OTEC-volumhistorikk er en hard produksjonsblokkering.

## Datakilder

### Otello

- rapporter og investorinformasjon for cash-, balanse-, ONA- og opsjonsankre;
- NewsWeb for regulatoriske meldinger og tilbakekjøp;
- Euronext delayed-data for løpende OTEC-markedsdata og recovery;
- validert historikkfil ved første bootstrap.

### Bemobi

- B3 COTAHIST for offisiell BMOB3-sluttkurs;
- CVM for regulatoriske metadata og dokumentstatus.

CVM-metadata alene får ikke automatisk finansiell effekt i NAV-modellen.

### Valuta

- ECB for BRL/NOK og USD/NOK via krysskurser.

## Oppdateringsjobber

### Rask oppdatering – hvert 30. minutt

```text
*/30 * * * *
```

Den raske banen håndterer blant annet:

- OTEC delayed/gap recovery;
- mulig OTEC EOD-finalisering;
- BMOB3 delayed/EOD;
- incremental NewsWeb;
- oppdatering av berørte cash-/ONA-/NAV-lag.

Fast Cron er verifisert i produksjon med `SUCCESS`.

### Full oppdatering – daglig

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

Full Workflow er kontrollert i produksjon med `SUCCESS`.

## Writer-lock og samtidighet

Rask Cron og Full Workflow bruker samme D1-baserte writer-lock i `runtime_state`.

Writer-lock er testet kontrollert i produksjon med sekvensen:

```text
normal kjøring -> blokkert under testlås -> normal kjøring gjenopptatt
```

Testlåsen ble fjernet etter kontrollen.

## D1 og gjenoppretting

D1 er produksjonsdatabasen. Bootstrap- og avstemmingsverktøyene støtter:

- deterministisk SQLite -> D1-eksport;
- manifest og radantall;
- logiske SHA-256-hashes;
- eksakt remote-paritet;
- fixture-sentinel mot CI-/testdata.

**D1 Time Travel** er primær mekanisme for kortsiktig full databasegjenoppretting. Restore-drill er bestått mot en separat drill-database ved å:

1. opprette kjent teststate;
2. ta bookmark;
3. gjøre en kontrollert endring;
4. restore til bookmark;
5. verifisere at endringen ble reversert.

## R2

R2-binding:

```text
SOURCE_ARCHIVE
```

R2 brukes til:

- råkilder fra full oppdatering;
- relevante NewsWeb-PDF-er;
- logiske D1-revisjonssnapshots.

Det logiske D1-snapshotet tas **hver søndag og ved månedsslutt**. En separat manuell drill kan tvinge snapshot uten D1-skriving.

Produksjonsdrillen 19.08.2026 verifiserte:

```text
23 tabeller
42 chunks
d1_writes = 0
manifest skrevet til R2
```

Snapshotene er chunket, gzip-komprimert og har SHA-256-manifest.

## Workers Paid og kostnadskontroll

Produksjonskonfigurasjonen bruker bevisst avgrensede Worker-grenser:

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
- WAF rate limiting på `/api/*`;
- Budget Alerts på **USD 1 og USD 5**.

D1-spesifikke Usage Based Billing-varsler er vurdert, men er **N/A på nåværende plan**. Kostnadskontrollen baseres derfor på Budget Alerts, Billable Usage og WAF cost guard.

Se `docs/cloudflare-paid-cost-guard.md`.

## Sikkerhet

Frontend leveres med blant annet:

- Content Security Policy;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- deaktivert kamera, mikrofon og geolokasjon via Permissions Policy.

FastAPI-dokumentasjon og OpenAPI-endepunkt er deaktivert i produksjons-API-et.

## Produksjonsdeploy

GitHub Action:

```text
.github/workflows/deploy-cloudflare.yml
```

Automatisk deploy starter kun etter vellykket `CI` på en push til `main`. En egen production environment-gate leser `CLOUDFLARE_DEPLOY_ENABLED`, og deploy-jobben bruker eksakt `head_sha` fra den vellykkede CI-kjøringen.

Workflowen:

1. verifiserer testet commit-SHA;
2. validerer produksjonsinnstillinger;
3. bygger frontend;
4. installerer pinnede Worker-/Wrangler-verktøy;
5. renderer produksjonskonfigurasjon;
6. kjører remote D1-migreringer;
7. deployer Python Worker og Workflows;
8. kjører obligatorisk HTTP-akseptanse;
9. ruller Worker tilbake hvis en kontroll etter deploy feiler.

Manuell deploy fra `main` er fortsatt tilgjengelig ved behov.

### Viktig om D1-migreringer

Worker-rollback ruller **ikke** tilbake D1-migreringer. Produksjonsmigreringer skal derfor være additive og bakoverkompatible. D1 Time Travel brukes ved behov for databasegjenoppretting.

## HTTP-akseptanse etter deploy

Den faktiske produksjonen testes etter deploy:

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

- riktig sidetittel og sikkerhetsheaders;
- `environment=cloudflare`;
- dashboard `ready=true`;
- historikk med datapunkter;
- økonomisk NAV klar;
- samme dato for økonomisk NAV og hoveddashboard;
- konsistent økonomisk/konservativ NAV;
- valuta-backtest klar med minst to perioder;
- tilbakekjøpsmotor uten `INSUFFICIENT_VOLUME_HISTORY`;
- modelldato maksimalt sju dager gammel.

## Lokal utvikling

SQLite-backenden brukes fortsatt til:

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
- `docs/ci-auto-deploy.md` – automatisk produksjonsdeploy
- `cloudflare/README.md` – Cloudflare-implementasjonen

## Neste finansielle kontrollpunkt

Neste planlagte rapportanker er **Otello 1H26 21.08.2026**. Når rapporten publiseres skal nye rapporterte cash-/balanseankre, ONA, opsjonsforpliktelse/-forutsetninger og driftskostnader avstemmes før de eventuelt blir nye kildebelagte modellankre.

Kontantfordeling per valuta oppdateres bare dersom ny rapport faktisk dokumenterer den. Modellen skal ikke gjette ukjent valutaeksponering.
