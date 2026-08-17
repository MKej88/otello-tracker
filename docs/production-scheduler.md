# Produksjonsscheduler for Otello-tracker

Otello-tracker kan kjøre den eksisterende `refresh_dashboard`-jobben automatisk i en egen Docker-container. Dette er laget for samme Docker Compose-oppsett som brukes lokalt og senere på Raspberry Pi.

## Standardoppsett

`docker compose up --build -d` starter tre tjenester:

- `otello-api` – FastAPI og SQLite-init/migreringer
- `otello-scheduler` – automatisk datainnhenting og NAV-refresh
- `otello-web` – dashboardet

Scheduleren venter til API-et er friskt før den starter. Deretter kjører den refresh med samme databasevolum som API-et.

Standard er:

```env
REFRESH_INTERVAL_MINUTES=30
REFRESH_RUN_ON_START=true
```

`REFRESH_INTERVAL_MINUTES` kan ikke settes lavere enn 5 minutter. Hensikten er å unngå aggressiv polling av eksterne datakilder.

## Endre intervall

Rediger lokal `.env`:

```env
REFRESH_INTERVAL_MINUTES=60
```

Start tjenestene på nytt:

```bash
docker compose up -d
```

## Ikke kjør refresh umiddelbart ved oppstart

```env
REFRESH_RUN_ON_START=false
```

Da venter scheduleren ett helt intervall før første refresh.

## Se status og logger

```bash
docker compose ps
```

Scheduler-logg:

```bash
docker compose logs -f scheduler
```

Hver kjøring skriver én kompakt JSON-linje, for eksempel:

```json
{"event":"refresh_complete","status":"ok","target_date":"2026-08-17","source_error_count":0,"dashboard_ready":true}
```

En `degraded` refresh stopper ikke scheduleren. Den fortsetter på neste intervall fordi den eksisterende refresh-pipelinen er laget for å beholde siste gyldige data når en ekstern kilde midlertidig feiler.

En uventet feil utenfor den vanlige fail-soft-håndteringen logges som `refresh_failed`, men prosessen fortsetter også da ved neste intervall.

## Manuell refresh ved behov

Scheduleren erstatter ikke muligheten til å kjøre en manuell refresh:

```bash
docker compose exec -T api python -m app.jobs.refresh_dashboard
```

Streng kontroll kan fortsatt kjøres manuelt:

```bash
docker compose exec -T api python -m app.jobs.refresh_dashboard --strict
```

## Raspberry Pi

Når prosjektet senere flyttes til Raspberry Pi, er det ikke nødvendig å installere Python eller cron på selve Pi-en utover det som allerede trengs for Docker. Scheduler-koden ligger i backend-imaget og startes av Docker Compose med `restart: unless-stopped`.

Etter omstart av Pi-en vil Docker kunne starte API, scheduler og web igjen, forutsatt at Docker er satt opp til å starte ved boot og Compose-stacken er startet som vanlig.
