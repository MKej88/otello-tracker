# Otello NAV-oversikt

Et privat investorverktøy for **Otello Corporation ASA**. Programmet samler
offentlige markeds- og selskapsdata og viser blant annet estimert NAV,
NAV-rabatt, Otellos investeringer, tilbakekjøp og viktige hendelser.

Produksjonsløsningen kjører på **Cloudflare Workers Paid**. API-et er skrevet i
Python, mens nettsiden er bygget med React og Vite.

## Dette finnes i programmet nå

Den aktive investorvisningen består av:

- **Oversikt** – nøkkeltall for OTEC, NAV, rabatt og investeringene;
- **NAV** – estimert økonomisk NAV og forklaring av endringene;
- **Historikk** – historisk NAV-rabatt for valgte perioder;
- **Tilbakekjøpsprogram** – gjennomførte kjøp, fremdrift og estimater;
- **Bemobi** – kurs, eierandel, regnskapstall og operasjonelle nøkkeltall;
- **Brasil** – renter, inflasjon, valuta og markedssignaler som er relevante for
  Bemobi;
- **Konsensus** – offentlige analytikerestimater for Bemobi;
- **Nyheter** – Otello- og Bemobi-meldinger og hendelseskalender;
- **Datakvalitet** – status for kilder, rapporter og oppdateringsjobber.

## Hvordan løsningen henger sammen

```text
Nettleser
   |
   v
Cloudflare Worker + Static Assets
   |
   |-- React/Vite-nettside
   |-- Python-API (/api/*)
   |
   +-- D1: produksjonsdatabase
   +-- R2: råkilder, PDF-er og revisjonssnapshots
   +-- Cron: rask oppdatering hvert 30. minutt
   +-- Workflow: full oppdatering kl. 03:35 UTC hver dag
```

`cloudflare/` er produksjonsimplementasjonen. `backend/` er en lokal
SQLite-basert referanse som brukes til utvikling og kontroll av beregningene;
den er ikke produksjonsdatabasen.

Mer teknisk informasjon finnes i [`docs/architecture.md`](docs/architecture.md).

## NAV-modellene

Programmet skiller mellom tre nivåer:

1. **CORE NAV** er Bemobi-markedsverdi pluss modellert eller rapportert
   kontantbeholdning.
2. **FULL NAV** legger øvrige nettoeiendeler og forpliktelser til CORE NAV.
3. **Økonomisk NAV** er investorvisningen. Den tar i tillegg hensyn til blant
   annet Life360-investeringen, dokumenterte valutaendringer, estimert drift,
   renteinntekter og økonomisk opsjonsoverheng.

Økonomisk NAV erstatter ikke CORE- og FULL-seriene. Lagene holdes adskilt slik
at det skal være mulig å se hva som er rapportert, og hva som er estimert.

Se [`docs/economic-nav.md`](docs/economic-nav.md) og
[`docs/option-liability.md`](docs/option-liability.md) for detaljene.

## Viktigste datakilder

| Område | Kilder og bruk |
| --- | --- |
| Otello | Selskapsrapporter og investorinformasjon gir ankere for kontanter, balanse, øvrige nettoeiendeler og opsjoner. NewsWeb brukes til børsmeldinger og tilbakekjøp. Euronext delayed-data brukes til OTEC-markedsdata og gjenoppretting. |
| Bemobi | B3 brukes til BMOB3-kurser, CVM til regulatoriske dokumenter og Bemobi IR til blant annet eierandel og analytikerdekning. Offentlige tredjepartstall brukes bare når de kan spores. |
| Life360 | Rapporterte beholdningsankere kombineres med lagrede LIF-markedsdata. Investeringen vises i økonomisk NAV uten å dobbelttelles i øvrige nettoeiendeler. |
| Valuta | Norges Bank er primærkilde for direkte BRL/NOK og USD/NOK. Eldre ECB-data beholdes som historisk kildegrunnlag og reserve. |
| Brasil | Offentlige brasilianske makrodata brukes i Brasil-visningen og som bakgrunn for vurderingen av Bemobi. |

CVM-metadata alene får ikke opprette eller endre finansielle fakta. Kilder som
påvirker beregningene skal kunne spores.

## Oppdatering og drift

- Den raske oppdateringen kjører hvert 30. minutt og henter lette,
  inkrementelle data som markedspriser og NewsWeb-meldinger.
- Den fulle oppdateringen kjører daglig kl. 03:35 UTC og håndterer tyngre
  kilder, avstemming, historikk, NAV-beregninger og R2-arkivering.
- Begge oppdateringsbanene bruker samme D1-baserte skrivelås for å unngå at de
  endrer de samme dataene samtidig.
- En skrivebeskyttet GitHub Actions-diagnose kontrollerer nattkjøringen og
  sentrale produksjonsdata.
- D1 Time Travel er primær databasegjenoppretting. Logiske R2-snapshots er et
  ekstra revisjons- og gjenopprettingslag.

Praktiske driftsrutiner står i [`docs/runbook.md`](docs/runbook.md).

## API

Cloudflare-API-et har versjon **0.13.1**. De aktive endepunktene er:

```text
GET /api/health
GET /api/dashboard/bootstrap
GET /api/dashboard/summary
GET /api/dashboard/report-status
GET /api/dashboard/runtime-status
GET /api/dashboard/economic
GET /api/dashboard/waterfall
GET /api/dashboard/fx-backtest
GET /api/dashboard/history
GET /api/dashboard/discount-history
GET /api/market/quotes
GET /api/buybacks/forecast
GET /api/buybacks/dashboard
GET /api/bemobi/dashboard
GET /api/bemobi/consensus
GET /api/bemobi/source-status
GET /api/brazil/dashboard
GET /api/news-events
```

Den lokale referanse-API-en i `backend/` har versjon **0.12.0**. Den brukes til
å teste finansielle beregninger og er ikke en kopi av hele produksjonsmiljøet.

## Lokal bruk med bare Python

Hvis du bare har Python, kan du kjøre referanse-API-et og Python-testene. Bruk
**Python 3.12**:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
PYTHONPATH=. python -m uvicorn app.main:app --reload
```

API-et blir tilgjengelig på `http://127.0.0.1:8000`. Interaktiv
API-dokumentasjon finnes på `http://127.0.0.1:8000/docs`.

Kjør testene i et eget terminalvindu med det samme virtuelle miljøet aktivert:

```bash
cd backend
PYTHONPATH=. python -m pytest -q
```

Dette er den anbefalte lokale arbeidsmåten når bare Python er tilgjengelig. Den
ferdige React-nettsiden og en lokal Cloudflare Worker kan ikke bygges med Python
alene; de krever også Node.js 22 og npm. Det er ikke nødvendig for å arbeide med
eller teste Python-beregningene.

## Deploy og sikkerhet

Endringer går via pull request og obligatorisk CI. Etter grønn CI på `main`
bygges og kontrolleres den eksakte commit-en før D1-migreringer og Worker blir
sendt til produksjon. Produksjonsendepunktene testes etterpå, og Worker kan
rulles tilbake hvis kontrollen feiler. D1-migreringer må være additive og
bakoverkompatible fordi de ikke rulles tilbake sammen med Worker.

Nettsiden leveres med vanlige sikkerhetsheadere. Hemmeligheter skal ligge i
GitHub eller Cloudflare, aldri i Git.

## Videre dokumentasjon

- [`docs/architecture.md`](docs/architecture.md) – produksjonsarkitektur
- [`docs/runbook.md`](docs/runbook.md) – drift, feil og gjenoppretting
- [`docs/migration-history.md`](docs/migration-history.md) – regler for D1-migreringer
- [`docs/economic-nav.md`](docs/economic-nav.md) – økonomisk NAV
- [`docs/option-liability.md`](docs/option-liability.md) – opsjonsmodellen
- [`docs/buyback-forecast.md`](docs/buyback-forecast.md) – tilbakekjøpsmodellen
- [`docs/cloudflare-paid-cost-guard.md`](docs/cloudflare-paid-cost-guard.md) – kostnadsvern
- [`docs/ci-auto-deploy.md`](docs/ci-auto-deploy.md) – automatisk produksjonsdeploy
- [`cloudflare/README.md`](cloudflare/README.md) – Cloudflare-implementasjonen
- [`ROADMAP.md`](ROADMAP.md) – planlagte forbedringer
