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

Fase 2 legger til et versjonert og kilde-/audit-sporbart datalag for markedsdata, FX, holdings, cash, tilbakekjøp, corporate actions, NAV, selskapsmeldinger og meglerestimater.

Se [docs/data-model.md](docs/data-model.md) for detaljert datamodell.

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
  +-- markedsdata / FX
  +-- Otello- og Bemobi-data
  +-- NAV-snapshots
  +-- meglerestimater / konsensus
  +-- kilde- og provenance-spor
```

Samme containere er ment å kunne kjøres på Windows under utvikling og senere på Raspberry Pi.

## Databaseprinsipper

- SQLite initialiseres automatisk ved appstart.
- Migreringer ligger i `backend/app/db/migrations/` og kjøres bare én gang.
- Foreign keys er aktivert på alle forbindelser.
- Produksjonsfilen bruker WAL-modus.
- Finansielle desimaltall lagres som tekst og beregnes med Python `Decimal` for å unngå flyttallsavrunding.
- Kildedata kan spores gjennom `sources`, `source_documents` og `provenance_records`.
- Rå dokumenter og vår klassifisering/tolkning holdes separat.

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
- Database-status: http://localhost:8000/api/system/database
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

## GitHub og secrets

Ikke commit `.env`, databasefiler eller API-nøkler. Produksjonsdata ligger utenfor Git-historikken.

## Neste fase

Fase 3 bygger historisk Otello-datagrunnlag fra primærkilder:

- Otello-rapporter og børsmeldinger
- Bemobi-beholdning over tid
- OTEC total-/egne-/utestående aksjer
- rapporterte cash-ankre
- relevante corporate actions
- første historiske NAV-ankerpunkter
