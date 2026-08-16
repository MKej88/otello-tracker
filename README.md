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
**Fase 8 – samlet refresh-pipeline:** ferdig  
**Fase 9 – FULL NAV:** kode/tester ferdig; live-backfill er neste kontroll

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
  +-- daglig cash
  +-- CORE NAV-snapshots
  +-- rapporterte/daglige øvrige nettoeiendeler
  +-- FULL NAV-snapshots
  +-- buybacks / corporate actions
  +-- meglerestimater / konsensus
  +-- kilde- og provenance-spor
```

Samme containere er ment å kunne kjøres på Windows under utvikling og senere på Raspberry Pi.

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

ONA beholdes i rapportens USD, konverteres med historisk USD/NOK og interpoleres i USD mellom rapportankrene. FULL NAV lagres som en separat serie og overskriver aldri CORE. Etter siste rapporterte ONA-anker merkes serien `FORECAST_PARTIAL`.

FULL NAV starter foreløpig 30.06.2022. 2021 holdes CORE-only fordi AdColony-transaksjonen skapte vesentlige fordrings-/skattebalanser som må dokumenteres særskilt før de kan legges inn.

## Databaseprinsipper

- SQLite initialiseres automatisk ved appstart.
- Migreringer ligger i `backend/app/db/migrations/` og kjøres bare én gang.
- Foreign keys er aktivert på alle forbindelser.
- Produksjonsfilen bruker WAL-modus.
- Finansielle desimaltall lagres som tekst og beregnes med Python `Decimal`.
- Kildedata spores gjennom `sources`, `source_documents` og `provenance_records`.
- Rå dokumenter og vår klassifisering/tolkning holdes separat.
- Senere restatements får prioritet når de superseder tidligere rapporterte balanser.
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
- Daglig CORE NAV-status: http://localhost:8000/api/nav/daily
- ONA-status: http://localhost:8000/api/nav/other-net-assets
- FULL NAV-status: http://localhost:8000/api/nav/full
- Dashboard summary: http://localhost:8000/api/dashboard/summary
- Dashboard historikk: http://localhost:8000/api/dashboard/history
- FastAPI docs: http://localhost:8000/docs

Dashboardet foretrekker FULL-serien når den finnes, og faller automatisk tilbake til CORE hvis FULL ennå ikke er bygget.

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

## Bygg NAV

CORE-only kan fortsatt bygges separat:

```bash
python -m app.jobs.rebuild_daily_nav
```

Den samlede refresh-pipelinen bygger nå hele kjeden:

```bash
python -m app.jobs.refresh_dashboard
```

Rekkefølge:

1. init/migrering + kuratert historikk
2. nylig ECB FX
3. gjeldende B3 BMOB3
4. nye Otello-buybacks
5. report-date CORE NAV
6. daglig cash
7. daglig CORE NAV
8. rapporterte ONA-ankre → NOK
9. daglig ONA
10. daglig FULL NAV
11. dashboard/status

En enkelt kildefeil stopper ikke resten av refreshen. Feilen legges i `source_errors`, siste lagrede data brukes videre, og totalstatus blir `degraded` når det er relevant.

OTEC oppdateres foreløpig ikke via en udokumentert scraper. En fersk CSV kan mates inn ved behov:

```bash
python -m app.jobs.refresh_dashboard --otec-csv /path/OTEC.csv
```

eller:

```bash
python -m app.jobs.refresh_dashboard --otec-investing-csv /path/OTEC-investing.csv
```

Bruk `--strict` dersom en scheduler/CI skal returnere feilstatus når refreshen ikke ender i `ok`.

## GitHub og secrets

Ikke commit `.env`, databasefiler, API-nøkler eller rå markedsdatafiler. Produksjonsdata ligger utenfor Git-historikken.
