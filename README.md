# OtelloTracker – investoroversikt for Otello

**[Åpne OtelloTracker](https://otellotracker.com)** · [Driftsdokumentasjon](docs/runbook.md) · [Arbeidsflyter](docs/github-actions.md) · [Videre utvikling](ROADMAP.md)

*Dokumentasjonen oppdatert 28. november 2026.*

OtelloTracker er et uavhengig investorverktøy for **Otello Corporation ASA (OTEC)**.
Det samler offentlige selskaps-, markeds- og makrodata for å følge estimert
substansverdi (NAV), rabatt, kapitalallokering, tilbakekjøp og utviklingen i
Bemobi og øvrige investeringer.

Produksjonsløsningen kjører på **Cloudflare Workers Paid**, med Python-API,
React/TypeScript og Vite, D1-database og R2-arkiv. Brukergrensesnittet er på norsk.

Tallene er indikative og kan være forsinket. Rapporterte selskapsopplysninger,
markedsobservasjoner og modellestimater skal holdes adskilt. Verktøyet er
ikke en offisiell selskapsrapport, kursprognose eller investeringsanbefaling.

## Investorvisninger

De tolv visningene er organisert i fire navigasjonsgrupper: Verdi, Kapital,
Bemobi og Informasjon.

- **Oversikt** – nøkkeltall for OTEC, NAV, rabatt og investeringene, oppside til
  NAV, teoretisk OTEC-kurs ved ettårsmedianen for NAV-rabatt og kommende hendelser
  med Bemobis kvartalsestimater;
- **NAV** – økonomisk og konservativ NAV, investeringer, kontanter,
  Alliance Venture Spring, Life360, opsjoner og forklaring av verdiendringer;
- **NAV-sensitivitet** – scenariomatrise og eksakte inndata for hvordan
  Bemobi-kurs og BRL/NOK påvirker NAV, rabatt og oppside, med justerbare
  intervaller og steg;
- **Historikk** – historisk NAV-rabatt og OTEC-kurs for valgte perioder, median
  og persentiler;
- **Tilbakekjøpsprogram** – gjennomførte kjøp, fremdrift og estimater;
- **Cash** – kontantbeholdning, kapitalallokering, ordinært utbytte og renter
  på egenkapital (JCP) fra Bemobi, med skille mellom annonserte og estimerte beløp;
- **Bemobi** – kurs, eierandel, regnskapstall og operasjonelle nøkkeltall;
- **BRL/NOK** – valutautvikling, drivere og beregnet effekt på NAV;
- **Brasil** – styringsrente, inflasjon, vekst, valuta, hendelser og Focus-undersøkelsen
  fra Brasils sentralbank. Prognoserevisjoner vises per prognoseår, adskilt fra
  endringer i dagens faktiske rentenivå;
- **Konsensus** – offentlige analytikerestimater for Bemobi, kvartalsforventninger
  per meglerhus, snitt og sammenligning med rapporterte kvartalstall;
- **Nyheter** – Otello- og Bemobi-meldinger, offisiell Bemobi-kalender og norske
  PDF-oversettelser når de er tilgjengelige, med kontrollert behandling av de
  siste 24 måneders gjeldende CVM-dokumenter;
- **Datakvalitet** – kilde- og datoferskhet, rapportstatus, oppdateringsjobber,
  avvik og dokumentbehandling.

Oversikten viser også **Bemobi siden Oslo Børs stengte**, med kursendring i BRL,
teoretisk OTEC-effekt og teoretisk OTEC-kurs. Beregningen bruker fast valutakurs
og en omtrentlig Bemobi-referanse rundt Oslo-sluttauksjonen. Kortet beholder
siste gyldige resultat frem til neste åpning på Oslo Børs kl. 09:00. Deretter
venter alle tre kortene (Bemobi, OTEC-effekt og BRL/NOK) på dagens Oslo-stenging,
uten å vise forrige måleperiodes beregninger. Valutakortet følger BRL/NOK frem
til neste Oslo-åpning, separat fra Bemobi-effekten. Manglende grunnlag vises tydelig.
Se [`docs/bemobi-etter-oslo.md`](docs/bemobi-etter-oslo.md) for metode og forbehold.

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
   +-- Workers AI: norske Bemobi-dokumentoversettelser
   +-- Email Routing: nattrapport når e-postbindingen er konfigurert
   +-- Cron: rask oppdatering, Oslo-referanser og etter-stenging-oppdatering
   +-- Cron -> Workflow: full oppdatering kl. 03:35 UTC hver dag
```

`cloudflare/` er produksjonsimplementasjonen. `backend/` er en lokal
SQLite-basert referanse som brukes til utvikling og kontroll av beregningene;
den er ikke produksjonsdatabasen.

GitHub Actions håndterer kodekontroll, produksjonsutrulling, skrivebeskyttet
produksjonsdiagnostikk, dokumentvedlikehold og sikkerhetskontroller.

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
Den konservative NAV-varianten viser alternative modellforutsetninger.

NAV-forklaringen skiller mellom kurs- og valutaeffekt for Bemobi, Life360,
Alliance Venture Spring, rapporterte kontanter, driftskostnader, renteinntekter
og tilbakekjøp. Bekreftede Bemobi-utdelinger vises som fordring frem til
utbetaling; overføringen fra fordring til kontanter skal ikke endre NAV.
Renter på egenkapital og ordinært utbytte skal ikke dobbelttelles i utbyttemodellen.

Se [`docs/economic-nav.md`](docs/economic-nav.md) og
[`docs/option-liability.md`](docs/option-liability.md) for detaljene.

## Viktigste datakilder

| Område | Kilder og bruk |
| --- | --- |
| Otello | Selskapsrapporter og investorinformasjon gir ankere for kontanter, balanse, øvrige nettoeiendeler og opsjoner. NewsWeb brukes til børsmeldinger og tilbakekjøp. Euronext delayed-data brukes til OTEC-markedsdata og gjenoppretting. |
| Bemobi | B3 for BMOB3-kurs og offisiell sluttkurs (COTAHIST), Yahoo Finance for volum og validert kursreserve. CVM og Bemobi IR for selskapsdokumenter, rapporterte tall, utdelinger, eierandel og analytikerdekning. Verifiserte originaler i R2 er reserve ved CVM-svikt. |
| Life360 | Rapporterte beholdningsankere og LIF-kurser fra Yahoo Finance; Life360 IR/LSEG som separat reserve ved transportfeil. Investeringen skal ikke dobbelttelles. |
| Valuta | Norges Bank for daglig BRL/NOK og USD/NOK; Exchangerate.dev for godkjent BRL/NOK-intradag. ECB beholdes som historisk kildegrunnlag, ikke som aktiv innhenting. |
| Brasil | Banco Central do Brasil (BCB), inkludert Focus/Olinda, og IBGE for makroserier og publiseringer. Investing.com brukes kun som sekundær kilde for hendelseskonsensus og publiseringstid der tilgjengelig. |

CVM-metadata alene får ikke opprette eller endre finansielle fakta. Kilder som
påvirker beregningene skal kunne spores. Forsinkede LAST-observasjoner skal
ikke fremstilles som offisielle sluttkurser. Kildesvikt eller manglende
verifisering skal synliggjøres fremfor å fylle hull med antakelser.

Se [kildehierarki og reserver](docs/kildehierarki-og-reserver.md) for aktiv
innhenting, reservekilder og historisk proveniens.

## Oppdatering og drift

- Den raske oppdateringen kjører hvert 30. minutt og henter lette,
  inkrementelle data som markedspriser og NewsWeb-meldinger.
- Exchangerate.dev BRL/NOK-intradag er aktivert for løpende estimert NAV
  etter at eier bekreftet tillatelse til bruk gjennom OtelloTrackers offentlige
  API-er 26.10.2026. Kilden sjekkes hvert 30. minutt via nøkkelfritt API,
  og Norges Bank beholdes for historikk og reserve. Se
  [integrasjonsnotatet](docs/exchangerate-dev-brlnok.md).
- Den fulle oppdateringen kjører daglig kl. 03:35 UTC og håndterer tyngre
  kilder, avstemming, historikk, NAV-beregninger og R2-arkivering.
  Det tilsvarer kl. 05:35 norsk sommertid og kl. 04:35 norsk vintertid.
  Worker-cron starter Workflow for foregående kalenderdag; etter hver raske
  oppdatering kontrolleres det om nattkjøringen mangler. En fast instans-ID
  hindrer duplikater. Feilede eller terminerte instanser restartes ikke automatisk.
- Rask og full oppdatering bruker samme D1-baserte skrivelås for å unngå at de
  endrer de samme dataene samtidig. Bemobi-referansen ved Oslo-stenging lagres
  separat og idempotent, slik at fulloppdateringen ikke blokkerer tidsvinduet.
- Bemobi-referansen forsøkes hentet hvert minutt kl. 16:37–16:43 norsk tid på
  ordinære Oslo-børsdager, og kl. 13:17–13:23 onsdag før påske. Kalender og lokal
  klokke filtrerer de ekstra UTC-triggerne før innhenting. Kortet i nettleseren
  oppdateres hvert andre minutt; ordinær kursinnhenting skjer hvert 30. minutt.
- Lettvektsoppdateringer kl. 16:47 og 16:55 norsk tid (13:27 og 13:35 på
  halv handelsdag) gjenoppretter eventuelt manglende Oslo-referanser og henter
  nyere Bemobi- og valutakurser. En separat kontroll følger opp Oslo-kortene.
- Konsensus følger rapporterte kvartaler og neste kvartals forventninger.
  Meglerhus gis lik vekt per måltall; ulike resultatdefinisjoner holdes adskilt.
  [Q3 2026-metoden og sammenligningstall](docs/bemobi-q3-expectations.md)
  beholdes som dokumentasjon av modell og historikk.
- Nye Bemobi-dokumenter behandles i oversettelseskøen. En separat arbeidsflyt
  følger opp et rullerende vindu på 24 måneder annenhver time.
- Skrivebeskyttet GitHub Actions-diagnostikk kontrollerer nattkjøringen og
  sentrale produksjonsdata, inkludert kildeferskhet, kursdekning, NAV og cache.
  Syntetisk ytelsesovervåkning følger responstider og cacheoppførsel.
- D1 Time Travel er primær databasegjenoppretting. Logiske R2-snapshots er et
  ekstra revisjons- og gjenopprettingslag.

Praktiske driftsrutiner står i [`docs/runbook.md`](docs/runbook.md).
Oppstart og gjenoppretting av nattkjøringen er beskrevet i
[`docs/nightly-trigger-recovery.md`](docs/nightly-trigger-recovery.md).

### Nattrapport og dokumentbehandling

Ved konfigurert e-postutsending sendes én rapport fra nattjobben, i HTML og
ren tekst. Status og kritiske avvik kommer først, deretter investor-NAV,
kontroller, kilder, dokumentbehandling og ressurs-/kjøringsdetaljer når de er
rapportert. Normal modellinformasjon er ikke et avvik. Senere uavhengige
produksjonskontroller inngår ikke i e-postens status.

Bemobi-oversettelser beholder originaldokumentets lenke. Workers AI brukes
på dokumenter med lesbart tekstgrunnlag, med kontroll av tall og datoer før
norsk PDF arkiveres i R2. Historisk behandling er avgrenset til verifiserte,
gjeldende CVM-dokumenter fra siste 24 måneder. Dokumenter uten lesbar tekst
kan kreve OCR; fullført historikk eller oversettelse av alle dokumenter er
ikke garantert.

Se [nattrapport](docs/nightly-email-report.md), [produksjonsovervåkning](docs/production-monitoring.md)
og [Bemobi-oversettelser](docs/bemobi-norsk-oversettelse.md).

## API

Aktiv API-versjon og utrullet Git-revisjon kan kontrolleres via
[`/api/health`](https://otellotracker.com/api/health). Endepunktene for
investorvisningen og driftskontroll omfatter:

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
GET /api/dashboard/nav-periods
GET /api/fx/dashboard
GET /api/market/quotes
GET /api/market/bemobi-after-oslo
GET /api/buybacks/forecast
GET /api/buybacks/dashboard
GET /api/buybacks/overview-status
GET /api/bemobi/dashboard
GET /api/bemobi/consensus
GET /api/bemobi/source-status
GET /api/overview/events
GET /api/brazil/dashboard
GET /api/news-events
```

Bemobi-dokumenter kan i tillegg ha en norsk PDF-oversettelse tilgjengelig via
`GET /api/bemobi-translations/{news_id}.pdf`.

Den lokale referanse-API-en i `backend/` har versjon **0.12.1**. Den brukes til
å teste finansielle beregninger og er ikke en kopi av hele produksjonsmiljøet.
Den har blant annet ikke bootstrap, Bemobi-etter-Oslo, Brasil-dashboard eller
produksjonens driftsstatusendepunkter.

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
Ved oppstart opprettes og migreres lokal SQLite automatisk, med kuratert
historikk som referansegrunnlag. Standardstien er `backend/data/otello.db`
når kommandoen kjøres fra `backend/`; den kan overstyres med `DATABASE_PATH`.

Kjør testene i et eget terminalvindu med det samme virtuelle miljøet aktivert:

```bash
cd backend
PYTHONPATH=. python -m pytest -q
```

Dette er den anbefalte lokale arbeidsmåten når bare Python er tilgjengelig. Den
ferdige React-nettsiden og en lokal Cloudflare Worker kan ikke bygges med Python
alene; de krever også Node.js 22 og npm. Det er ikke nødvendig for å arbeide med
eller teste Python-beregningene.

## Lokal bruk av nettsiden

Start først referanse-API-et som beskrevet over. I et nytt terminalvindu kan du
deretter starte nettsiden med Node.js **22.12 eller nyere i 22-serien**:

```bash
cd frontend
npm ci
npm run dev
```

Åpne `http://localhost:3000`. Vite videresender lokale `/api`-kall til
referanse-API-et på `http://localhost:8000`. Fordi referanse-API-et ikke er en
full kopi av produksjonen, kan enkelte produksjonsdata eller statusfelt mangle
lokalt.

Frontend-tester og produksjonsbygg kan kjøres fra `frontend/`:

```bash
npm test
npm run build
```

## Produksjonsutrulling og sikkerhet

Endringer går via pull request og obligatorisk CI: backend, frontend,
D1-paritet, Cloudflare Worker og Docker-regresjon. Etter vellykket CI på
`main` kontrolleres produksjonsporten. Utrulling bruker GitHubs egen
`github.sha`; innsendt `tested_sha` fungerer bare som likhetskontroll.
Manuell utrulling er begrenset til `main`.

Ved aktivert automatisk utrulling sammenlignes faktisk aktiv produksjonsrevisjon
med testet main. Rene dokumentasjonsendringer og eksplisitt tillatte
offline-verktøy kan hoppe over utrulling, men ikke full CI. Ukjent revisjon
eller ukjent endring beholder ordinær utrulling.

Før remote D1-migreringer valideres produksjonskonfigurasjon, Worker-bundle og
nødvendige runtime-forutsetninger. Etter utrulling verifiseres eksakt revisjon
og sentrale API-datakontrakter mot offentlig produksjon. Worker kan rulles
tilbake hvis etterkontrollen feiler. D1-migreringer skal være additive og
bakoverkompatible, siden de ikke rulles tilbake sammen med Worker.

Sikkerhetsarbeidet omfatter CodeQL (Python, JavaScript/TypeScript og Actions),
Zizmor, Python-avhengighetskontroll, dependency review og OpenSSF Scorecard.
Actions er festet til commit-SHA der de brukes i produksjonsarbeidsflyten,
og checkout lagrer ikke Git-legitimasjon. Hemmeligheter skal ligge i GitHub
eller Cloudflare, aldri i Git. Produksjonen bruker sikkerhetsheadere og
WAF-/kostnadsvern for API-et.

### GitHub Actions

| Nummer | Område |
| --- | --- |
| 01–03 | CI, produksjonsutrulling og konfigurasjonsvalidering |
| 10–14 | Produksjonsdiagnostikk, manuell fulloppdatering, ytelse og Oslo-kontroll |
| 20–26 | Bemobi-dokumenter, oversettelser, speiling og gjenoppretting |
| 30 | Kontroll av sikkerhetskopier |
| 40–43 | Kode-, arbeidsflyt-, avhengighets- og sikkerhetsanalyse |
| 50 | Validering av tilbakekjøpsmodell |

Se [fullstendig arbeidsflytoversikt](docs/github-actions.md) for navn, filnavn
og avgrensning av produksjonsskriving. Historiske arbeidsflyter beholdes
i [arkivet](docs/archive/github-actions/README.md).

## Videre dokumentasjon

- [`docs/architecture.md`](docs/architecture.md) – produksjonsarkitektur
- [`docs/runbook.md`](docs/runbook.md) – drift, feil og gjenoppretting
- [`docs/github-actions.md`](docs/github-actions.md) – nummererte arbeidsflyter
- [`docs/production-monitoring.md`](docs/production-monitoring.md) – driftskontroll og datakvalitet
- [`docs/nightly-email-report.md`](docs/nightly-email-report.md) – nattrapport
- [`docs/kildehierarki-og-reserver.md`](docs/kildehierarki-og-reserver.md) – kildeprioritet og reservekilder
- [`docs/production-performance-followup.md`](docs/production-performance-followup.md) – syntetisk ytelsesovervåkning
- [`docs/migration-history.md`](docs/migration-history.md) – regler for D1-migreringer
- [`docs/economic-nav.md`](docs/economic-nav.md) – økonomisk NAV
- [`docs/option-liability.md`](docs/option-liability.md) – opsjonsmodellen
- [`docs/buyback-forecast.md`](docs/buyback-forecast.md) – tilbakekjøpsmodellen
- [`docs/bemobi-etter-oslo.md`](docs/bemobi-etter-oslo.md) – Bemobi-bevegelse og teoretisk OTEC-effekt etter Oslo-stenging
- [`docs/bemobi-q3-expectations.md`](docs/bemobi-q3-expectations.md) – offentlige kvartalsestimater og rapporterte sammenligningstall
- [`docs/bemobi-norsk-oversettelse.md`](docs/bemobi-norsk-oversettelse.md) – norske PDF-oversettelser via Workers AI
- [`docs/nightly-trigger-recovery.md`](docs/nightly-trigger-recovery.md) – nattkjøring, duplikatvern og gjenoppretting
- [`docs/cloudflare-paid-cost-guard.md`](docs/cloudflare-paid-cost-guard.md) – kostnadsvern
- [`docs/ci-auto-deploy.md`](docs/ci-auto-deploy.md) – automatisk produksjonsdeploy
- [`cloudflare/README.md`](cloudflare/README.md) – Cloudflare-implementasjonen
- [`ROADMAP.md`](ROADMAP.md) – planlagte forbedringer
