# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med mål om:

- løpende Otello-NAV
- historisk NAV og NAV-rabatt
- Otello-tilbakekjøp med korrekt cash-timing
- Bemobi-eksponering, utbytte/JCP og selskapsmeldinger
- Bemobi-meglerkonsensus før kvartalsrapporter
- datakildestatus og senere e-postrapporter

## Status

**Fase 1 – fundament:** ferdig  
**Fase 2 – SQLite og datamodell:** ferdig  
**Fase 3 – historiske Otello-rapportankre:** ferdig  
**Fase 4 – historiske markedsdata:** ferdig og live-validert  
**Fase 5 – daglig cash og CORE NAV:** ferdig og live-validert  
**Fase 6 – buybacks/cash-avstemming:** ferdig for kjent historikk  
**Fase 7 – live dashboard:** ferdig  
**Fase 8 – samlet refresh-pipeline:** ferdig  
**Fase 9/9.1 – FULL NAV + Bemobi-fordringer:** ferdig  
**Fase 9.2 – integrity/security hardening:** ferdig  
**Fase 9.3 – NewsWeb originalkilde og daglige buyback-transaksjoner:** ferdig og merget  
**Fase 9.4 – full NewsWeb-historikk fra 2020:** implementert, siste live-validering/PR gjenstår

Se [PHASE.md](PHASE.md) for detaljert fremdrift og [docs/data-model.md](docs/data-model.md) for datamodellen.

## Arkitektur

```text
Browser
  |
  v
Nginx / React frontend
  |
  | /api/*
  v
FastAPI backend (kun internt Docker-nettverk)
  |
  v
SQLite
  |
  +-- B3 BMOB3-kurser
  +-- Euronext/kuratert OTEC-kurshistorikk
  +-- ECB BRL/NOK og USD/NOK
  +-- Oslo Børs NewsWeb originalmeldinger/vedlegg
  +-- Otello/Bemobi historikk
  +-- daglig cash
  +-- CORE NAV-snapshots
  +-- rapporterte/daglige øvrige nettoeiendeler
  +-- FULL NAV-snapshots
  +-- buybacks / corporate actions
  +-- meglerestimater / konsensus
  +-- kilde- og provenance-spor
```

Samme containere er ment å kunne kjøres på Windows under utvikling og senere på Raspberry Pi. Web-porten bindes som standard til `127.0.0.1`; FastAPI-porten publiseres ikke direkte til hosten. Dette passer Cloudflare Tunnel-oppsettet og hindrer at API-et omgår Access via Pi-ens LAN-IP.

## NAV-definisjoner

`CORE NAV` er:

```text
Bemobi markedsverdi + modellert/rapportert cash
```

`FULL NAV` er:

```text
CORE NAV + øvrige nettoeiendeler/-forpliktelser (ONA)
```

Rapportert ONA beregnes fra Otellos konsoliderte balanse som:

```text
Total assets - cash - Bemobi carrying value - total liabilities
```

ONA beholdes i rapportens USD, konverteres med historisk USD/NOK og interpoleres i USD mellom rapportankrene. Bemobi-utbyttefordringer modelleres separat fra base ONA fra rettighetsdato til betalingsdato for å unngå dobbeltelling mot cash. FULL NAV lagres som en separat serie og overskriver aldri CORE. Dashboardet foretrekker bare FULL når FULL er oppdatert til samme dato som CORE.

FULL NAV starter foreløpig 30.06.2022. 2021 holdes CORE-only fordi AdColony-transaksjonen skapte vesentlige fordrings-/skattebalanser som må dokumenteres særskilt før de kan legges inn.

## Datakilder

- **B3 COTAHIST:** offisiell BMOB3 EOD-historikk, ujustert for corporate actions.
- **ECB:** BRL/NOK og USD/NOK krysskurser.
- **Euronext:** OTEC-priser og Otello-selskapsmeldinger/provenance.
- **Oslo Børs NewsWeb:** offisiell originalkilde for OTEC-meldinger og vedlegg. Trackeren kan hente hele OTEC-arkivet fra 2020 og transaksjons-PDF-er for tilbakekjøp.
- **Otello IR:** kuraterte rapporter og eldre utstedermeldinger.
- **MFN:** sekundær mirror/discovery-fallback; får aldri overskrive sterkere offisielle fakta.
- **Investing.com CSV:** manuell historisk OTEC-fallback med tydelig kvalitetsmerking; ikke automatisert scraping.

### Full NewsWeb-historikk

Første backfill spør NewsWeb etter alle OTEC-meldinger fra `2020-01-01`. Første OTEC-melding som faktisk finnes i dette vinduet er 11.02.2020. En full live-validering fant 539 meldinger gjennom 14.08.2026.

Trackeren speiler ikke hele NewsWeb-innholdet. For arkivet lagres message-ID, publiseringstid, tittel, URL, klassifisering, attachment-metadata og SHA256 av meldingsteksten. Full meldingstekst og PDF-er lagres ikke permanent. Etter første backfill bruker refresh-jobben 14 dagers overlapp fra siste lagrede melding i stedet for å hente hele historikken på nytt.

Meldinger klassifiseres deterministisk som blant annet `RESULTS`, `BUYBACK`, `DIVIDEND`, `JCP`, `CAPITAL`, `M_AND_A`, `GUIDANCE`, `CORPORATE` eller `OTHER`. `OTHER` merkes `REVIEW_REQUIRED`. **Klassifisering alene kan aldri endre NAV eller cash.** Bare separat verifiserte, testbare hendelser får finansiell modellvirkning.

Phase 9.4 har blant annet verifisert tre store 2021-tender-buybacks og tilhørende treasury/share-count-hendelser, samt NewsWeb-meldingen om USD 100m AdColony-betaling 27.10.2021. USD-beløpet får bare NOK-verdi når historisk ECB USD/NOK finnes. Et feilaktig eldre provenance-oppslag ble også avdekket: message ID `532327` tilhører ikke OTEC; korrekt NewsWeb completion-melding for tenderen 10.05.2021 er `532648`.

### NewsWeb og daglige buybacks

Ukesmeldingen lagres fortsatt som audit-/avstemmingsfaktum. Når NewsWeb-meldingen har et `Transaksjonsoversikt`-vedlegg:

1. PDF-en hentes transient fra NewsWeb attachment-API.
2. Individuelle `B OTEC`-handler parses deterministisk.
3. Hver linje avstemmes `antall × kurs = beløp`.
4. Dagene aggregeres og avstemmes mot ukens aksjetall, beløp og VWAP.
5. Cash bruker deretter faktiske handelsdatoer (`OTELLO_BUYBACK_DAILY`) i stedet for å legge hele ukesbeløpet på periodens sluttdato.

Hvis et historisk NewsWeb-vedlegg mangler, beholdes Phase 9.2-fallbacken: en ukessum som krysser et rapportert cash-anker ekskluderes konservativt fra eksplisitt post-anchor cash og absorberes av ankerresidualen. Systemet later ikke som daglig timing er kjent.

Historiske NewsWeb-buyback-meldinger har flere dokumenterte tekstformater. 2023-parseren har derfor en strengt avgrenset legacy-wrapper for utstederskrivefeilen `Sine the initiation` og første statusuke som mangler separat kumulativ/treasury-linje. Midt i et program tillates ikke slik inferens.

## Datakvalitet

- SQLite initialiseres automatisk ved appstart.
- Migreringer ligger i `backend/app/db/migrations/` og kjøres bare én gang.
- Foreign keys er aktivert på alle forbindelser; produksjonsfilen bruker WAL.
- Finansielle desimaltall lagres som tekst og beregnes med Python `Decimal`.
- Kildedata spores gjennom `sources`, `source_documents` og `provenance_records`.
- Rå dokumenter og vår klassifisering/tolkning holdes separat.
- Senere restatements får prioritet når de superseder tidligere rapporterte balanser.
- NAV skiller mellom `BACKFILLED`, `ESTIMATED` og `DEGRADED`.
- Manglende/forsinkede kilder gir synlig degradert status; de erstattes ikke med oppdiktede verdier.
- Lavere prioriterte buyback-kilder kan kontrollere, men ikke overskrive, sterkere fakta.

## Første oppstart med Docker

På Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

Åpne dashboardet på:

```text
http://localhost:3000
```

API-et nås gjennom nginx på samme origin, for eksempel:

```text
http://localhost:3000/api/health
http://localhost:3000/api/system/database
http://localhost:3000/api/system/history
http://localhost:3000/api/system/market-data
http://localhost:3000/api/nav/daily
http://localhost:3000/api/nav/other-net-assets
http://localhost:3000/api/nav/full
http://localhost:3000/api/dashboard/summary
http://localhost:3000/api/dashboard/history
```

FastAPI-port `8000` er ikke publisert direkte fra Docker Compose.

## Historisk markedsdata-backfill

Kommandoene kjøres i backend-containeren eller direkte fra `backend/` med `PYTHONPATH=.`.

### ECB – BRL/NOK og USD/NOK

```bash
python -m app.jobs.backfill_market_data --ecb --start 2021-02-10
```

### B3 – BMOB3

```bash
python -m app.jobs.backfill_market_data --b3-year 2021 --b3-year 2022 --b3-year 2023 --b3-year 2024 --b3-year 2025 --b3-year 2026
```

B3-nedlasteren har retry. Manuell ZIP kan også importeres:

```bash
python -m app.jobs.backfill_market_data --b3-file 2025:/path/COTAHIST_A2025.ZIP
```

### OTEC

Euronext CSV:

```bash
python -m app.jobs.backfill_market_data --otec-csv /path/OTEC.csv --otec-date-order DMY
```

Gratis Investing-export støttes som historisk fallback. Pre-09.08.2022-data merkes `RECONSTRUCTED` fordi NOK 21-utdelingen reverseres:

```bash
python -m app.jobs.backfill_market_data --otec-investing-csv /path/OTEC-investing.csv
```

## Refresh og NAV

CORE-only kan fortsatt bygges separat:

```bash
python -m app.jobs.rebuild_daily_nav
```

Den samlede refresh-pipelinen:

```bash
python -m app.jobs.refresh_dashboard
```

Rekkefølge:

1. init/migrering + kuratert historikk
2. nylig ECB FX
3. gjeldende B3 BMOB3
4. full/incrementell NewsWeb OTEC-arkivoppdatering
5. separat verifiserte historiske NewsWeb-hendelser
6. sekundær buyback-fallback + offisiell NewsWeb ukes-/vedleggsdata
7. NewsWeb daglig buyback → cash-sync der avstemt
8. report-date CORE NAV
9. daglig cash
10. daglig CORE NAV
11. rapporterte ONA-ankre → NOK
12. daglig ONA
13. daglig FULL NAV
14. dashboard/status

En enkelt kildefeil stopper ikke resten av refreshen. Feilen legges i `source_errors`, siste lagrede data brukes videre, og totalstatus blir `degraded` når det er relevant.

OTEC-kurs oppdateres foreløpig ikke via en udokumentert scraper. En fersk CSV kan mates inn ved behov:

```bash
python -m app.jobs.refresh_dashboard --otec-csv /path/OTEC.csv
```

eller:

```bash
python -m app.jobs.refresh_dashboard --otec-investing-csv /path/OTEC-investing.csv
```

Bruk `--strict` dersom en scheduler/CI skal returnere feilstatus når refreshen ikke ender i `ok`.

## GitHub og secrets

Ikke commit `.env`, databasefiler, API-nøkler eller rå markedsdata-/NewsWeb-PDF-er. Produksjonsdata ligger utenfor Git-historikken.
