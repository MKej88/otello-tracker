# Produksjonsscheduler for Otello-tracker

Otello-tracker kjører automatisk datainnhenting og NAV-refresh i en egen Docker-container. Samme Compose-oppsett brukes lokalt og i cloud-produksjon.

## Standardoppsett

`docker compose up --build -d` starter tre tjenester:

- `otello-api` – FastAPI og SQLite-init/migreringer
- `otello-scheduler` – automatisk datainnhenting og NAV-refresh
- `otello-web` – dashboardet/Nginx

Scheduleren venter til API-et er friskt før den starter. API og scheduler må ha samme persistente `/data`-mount. I cloud settes dette med `DATA_DIR` til en varig disk på hosten.

Standard er:

```env
REFRESH_INTERVAL_MINUTES=30
REFRESH_RUN_ON_START=true
FULL_REFRESH_INTERVAL_MINUTES=1440
BACKUP_INTERVAL_MINUTES=1440
```

`REFRESH_INTERVAL_MINUTES` kan ikke settes lavere enn 5 minutter. Hensikten er å unngå aggressiv polling av eksterne datakilder.

## Endre intervall

Rediger `.env` på produksjonshosten:

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

En `degraded` refresh stopper ikke scheduleren. Den fortsetter på neste intervall fordi refresh-pipelinen beholder siste gyldige data når en ekstern kilde midlertidig feiler.

En uventet feil utenfor den vanlige fail-soft-håndteringen logges som `refresh_failed`, men prosessen fortsetter ved neste intervall.

## Manuell refresh ved behov

```bash
docker compose exec -T api python -m app.jobs.refresh_dashboard
```

Streng kontroll:

```bash
docker compose exec -T api python -m app.jobs.refresh_dashboard --strict
```

## Cloud-drift

Cloud-produksjon forutsetter én aktiv app-host/region så lenge SQLite brukes. API og scheduler skal derfor ikke skaleres til flere verter som skriver til samme databasefil.

Produksjonshosten skal ha:

- persistent disk for `DATA_DIR`;
- restart-policy for containerne;
- HTTPS/reverse proxy foran `web`;
- bare web-tjenesten eksponert eksternt;
- off-host backup eller provider-snapshot i tillegg til `/data/backups`.

Ved reboot eller deploy starter Compose API, scheduler og web igjen med samme persistente database. Verifiser `job_runs` etter deploy og kjør `preflight --strict` etter større modell-/databaseendringer.

Se `docs/cloud-deployment.md` og `docs/production-readiness.md`.
