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
**Fase 4 – markedsdata/NAV-motor:** kode ferdig, full runtime-backfill gjenstår

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
  +-- Euronext OTEC-kurser
  +-- ECB BRL/NOK og USD/NOK
  +-- Otello/Bemobi historikk
  +-- CORE/FULL NAV-snapshots
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
- CORE NAV-status: http://localhost:8000/api/nav/core-anchors
- FastAPI docs: http://localhost:8000/docs

## Fase 4 – markedsdata-backfill

Kommandoene kjøres i backend-containeren eller direkte fra `backend/` med `PYTHONPATH=.`.

### ECB – BRL/NOK og USD/NOK

```bash
python -m app.jobs.backfill_market_data --ecb --start 2021-02-10
```

ECB leverer BRL, NOK og USD som referansekurser mot EUR. Systemet beregner deretter BRL/NOK og USD/NOK eksakt med `Decimal`.

### B3 – BMOB3

Automatisk årsfil:

```bash
python -m app.jobs.backfill_market_data --b3-year 2021 --b3-year 2022 --b3-year 2023 --b3-year 2024 --b3-year 2025 --b3-year 2026
```

B3 kan tidvis kreve CAPTCHA. Hvis automatisk nedlasting stopper, last ned årsfilen fra B3 og importer ZIP-filen direkte:

```bash
python -m app.jobs.backfill_market_data --b3-file 2025:/path/COTAHIST_A2025.ZIP
```

### Euronext – OTEC

Euronext Live har eksport av historiske data til CSV. Eksporter OTEC (`NO0010040611-XOSL`) med datoformat `dd/mm/yy` og importer:

```bash
python -m app.jobs.backfill_market_data --otec-csv /path/OTEC.csv --otec-date-order DMY
```

Parseren håndterer både komma/semikolon som skilletegn og punkt/komma som desimalskilletegn.

### Bygg report-date CORE NAV

Når BMOB3 + ECB er importert kan CORE NAV beregnes. OTEC-kurs er valgfri for NAV, men kreves for rabatt:

```bash
python -m app.jobs.backfill_market_data --rebuild-nav
```

`CORE` betyr bevisst kun **markedsverdi av Bemobi + rapportert cash**. Andre nettoeiendeler/gjeld er ikke satt inn som om de var kjent; dette dokumenteres i hvert snapshot. Når de er rekonstruert oppgraderes modellen til `FULL` NAV.

## GitHub og secrets

Ikke commit `.env`, databasefiler, API-nøkler eller rå markedsdatafiler. Produksjonsdata ligger utenfor Git-historikken.
