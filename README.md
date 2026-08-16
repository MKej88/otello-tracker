# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med mål om:

- løpende Otello-NAV
- historisk NAV og NAV-rabatt
- Otello-tilbakekjøp
- Bemobi-eksponering, utbytte/JCP og selskapsmeldinger
- Bemobi-meglerkonsensus før kvartalsrapporter
- datakildestatus og senere e-postrapporter

## Fase 1 – fundament

Denne første versjonen inneholder:

- FastAPI-backend
- React + TypeScript-frontend
- Docker Compose
- health-endepunkt
- mørkt dashboard-skjelett
- GitHub Actions-CI
- `.env.example`
- lokal datafolder for senere SQLite-database

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
SQLite (fase 2)
```

Samme containere er ment å kunne kjøres på Windows under utvikling og senere på Raspberry Pi.

## Første oppstart med Docker

1. Kopier miljøfilen:

```bash
cp .env.example .env
```

På Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

2. Start:

```bash
docker compose up --build -d
```

3. Åpne:

- Dashboard: http://localhost:3000
- API health: http://localhost:8000/api/health
- FastAPI docs: http://localhost:8000/docs

4. Se status:

```bash
docker compose ps
```

5. Se logger:

```bash
docker compose logs -f
```

6. Stopp:

```bash
docker compose down
```

## GitHub

Ikke commit `.env`, databasefiler eller API-nøkler.

## Neste fase

Fase 2 blir datamodellen og SQLite:

- instruments
- market_prices
- fx_rates
- bemobi_holdings
- otello_share_counts
- treasury_shares
- cash_anchors
- cash_movements
- buybacks
- corporate_actions
- dividends
- nav_snapshots
- source_documents
- company_news
- broker_estimates
- consensus_snapshots
- job_runs
- source_health
