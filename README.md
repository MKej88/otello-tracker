# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med mål om:

- løpende Otello-NAV
- historisk NAV og NAV-rabatt
- Otello-tilbakekjøp
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
**Fase 8 – samlet refresh-pipeline:** under ferdigstilling

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
FastAPI backend
  |
  v
SQLite
  |
  +-- B3 BMOB3-kurser
  +-- Euronext/kuratert OTEC-kurshistorikk
  +-- ECB BRL/NOK og USD/NOK
  +-- Otello/Bemobi historikk
  +-- daglig cash + CORE/FULL NAV-snapshots
  +-- buybacks / corporate actions
  +-- meglerestimater / konsensus
  +-- kilde- og provenance-spor
```

Samme containere er ment å kunne kjøres på Windows under utvikling og senere på Raspberry Pi.

## Databaseprinsipper

- SQLite initialiseres automatisk ved appstart.
- Migreringer ligger i `backend/app/db/migrations/` og kjøres bare én gang.
- Foreign keys er aktivert på alle forbindelser.
- Produksjonsfilen bruker WAL-modus.
- Finansielle desimaltall lagres som tekst og beregnes med Python `Decimal`.
- Kildedata spores gjennom `sources`, `source_documents` og `provenance_records`.
- Rå dokumenter og vår klassifisering/tolkning holdes separat.
- Historisk NAV skiller eksplisitt mellom `CORE` (Bemobi + cash) og senere `FULL` NAV.
- Manglende/forsinkede kilder gir synlig degradert status; de erstattes ikke med oppdiktede verdier.

## Første oppstart med Docker

På Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

Åpne:

- Dashboard: http://localhost:3000
- API health: http://localhost:8000/api/health
- Database-status: http://localhost:8000/api/system/database
- Historikkstatus: http://localhost:8000/api/system/history
- Markedsdatastatus: http://localhost:8000/api/system/market-data
- Daglig NAV-status: http://localhost:8000/api/nav/daily
- Dashboard summary: http://localhost:8000/api/dashboard/summary
- Dashboard historikk: http://localhost:8000/api/dashboard/history
- FastAPI docs: http://localhost:8000/docs

## Historisk markedsdata-backfill

Kommandoene kjøres i backend-containeren eller direkte fra `backend/` med `PYTHONPATH=.`.

### ECB – BRL/NOK og USD/NOK

```bash
python -m app.jobs.backfill_market_data --ecb --start 2021-02-10
```

ECB leverer BRL, NOK og USD som referansekurser mot EUR. Systemet beregner deretter BRL/NOK og USD/NOK eksakt med `Decimal`.

### B3 – BMOB3

```bash
python -m app.jobs.backfill_market_data --b3-year 2021 --b3-year 2022 --b3-year 2023 --b3-year 2024 --b3-year 2025 --b3-year 2026
```

B3 kan tidvis avbryte store årsfil-nedlastinger. Nedlasteren prøver automatisk på nytt. Manuell ZIP kan også importeres:

```bash
python -m app.jobs.backfill_market_data --b3-file 2025:/path/COTAHIST_A2025.ZIP
```

### OTEC

Historisk OTEC kan importeres fra Euronext CSV:

```bash
python -m app.jobs.backfill_market_data --otec-csv /path/OTEC.csv --otec-date-order DMY
```

Gratis Investing-export støttes også som historisk fallback. Pre-09.08.2022-data merkes `RECONSTRUCTED` fordi NOK 21-utdelingen må reverseres:

```bash
python -m app.jobs.backfill_market_data --otec-investing-csv /path/OTEC-investing.csv
```

## Bygg daglig NAV

```bash
python -m app.jobs.rebuild_daily_nav
```

`CORE` betyr bevisst **markedsverdi av Bemobi + modellert/rapportert cash**. Andre nettoeiendeler/gjeld er foreløpig ikke lagt til som om de var kjent. Post-siste rapporterte cash-anker merkes `FORECAST_PARTIAL`.

## Samlet refresh

Fase 8 samler de daglige operasjonene i én kommando:

```bash
python -m app.jobs.refresh_dashboard
```

Standardkjøringen:

1. initialiserer/migrerer databasen og seeder kuratert historikk
2. oppdaterer nylige ECB-valutakurser
3. laster/importerer gjeldende B3 COTAHIST-år for BMOB3
4. samler nye Otello-buyback-meldinger
5. bygger report-date CORE NAV på nytt
6. bygger daglig cash på nytt
7. bygger daglig CORE NAV og rabatt på nytt
8. returnerer markedsdata-, buyback-, cash-, NAV- og dashboardstatus

En enkelt kildefeil stopper ikke resten av refreshen. Feilen legges i `source_errors`, siste lagrede data brukes videre, og totalstatus blir `degraded` når det er relevant.

OTEC oppdateres foreløpig ikke via en udokumentert scraper. En fersk CSV kan mates inn ved behov:

```bash
python -m app.jobs.refresh_dashboard --otec-csv /path/OTEC.csv
```

eller historisk Investing-CSV:

```bash
python -m app.jobs.refresh_dashboard --otec-investing-csv /path/OTEC-investing.csv
```

Bruk `--strict` dersom en scheduler/CI skal returnere feilstatus når refreshen ikke ender i `ok`.

## GitHub og secrets

Ikke commit `.env`, databasefiler, API-nøkler eller rå markedsdatafiler. Produksjonsdata ligger utenfor Git-historikken.
