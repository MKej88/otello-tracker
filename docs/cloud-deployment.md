# Cloud deployment

Otello-trackeren er nå lagt opp som en **cloud-first Docker-applikasjon**. Standard produksjonsarkitektur er én cloud-host/container-host med Docker Compose og en persistent disk. Dette bevarer den eksisterende FastAPI + scheduler + SQLite-arkitekturen uten unødvendig migrering av datamodellen.

## Arkitektur

```text
Internet
  |
  v
Cloud edge / HTTPS reverse proxy
  |
  v
web (Nginx + React)  <--- eneste offentlige app-port
  |
  | /api/* på privat Docker-nett
  v
api (FastAPI)  -------- scheduler
      |                    |
      +--------+-----------+
               v
        persistent /data
        SQLite + backups
```

Viktige forutsetninger:

- `api` og `scheduler` skal bruke **samme persistente disk**;
- `/data` må ligge på varig cloud storage, ikke containerens ephemeral filesystem;
- bare `web` skal eksponeres eksternt;
- HTTPS termineres hos cloud-provider, load balancer eller annen edge/reverse proxy;
- SQLite-oppsettet er laget for én aktiv app-host/region. Ikke horisontalskaler API/scheduler over flere verter med samme SQLite-fil.

## 1. Opprett cloud-host

Bruk en Linux-basert cloud VM/container-host med Docker Engine og Docker Compose. Fest en persistent disk og monter den på for eksempel:

```text
/var/lib/otello
```

Katalogen skal overleve deploy, reboot og image-bytte.

## 2. Klon repo og opprett produksjonsmiljø

```bash
git clone <repo-url>
cd otello-tracker
cp .env.production.example .env
```

Sett minst:

```env
APP_ENV=production
WEB_BIND=0.0.0.0
WEB_PORT=3000
DATA_DIR=/var/lib/otello
DATABASE_PATH=/data/otello.db
BACKUP_DIR=/data/backups
CORS_ORIGINS=https://din-endelige-domene.example
TZ=Europe/Oslo
```

Secrets skal ligge i cloud-providerens secret store eller i hostens `.env`, aldri i Git.

## 3. Persistent data

Opprett katalogene på den persistente disken:

```bash
sudo mkdir -p /var/lib/otello/raw /var/lib/otello/backups
```

`compose.yaml` monterer `${DATA_DIR}` som `/data` i både API og scheduler. Dermed brukes samme SQLite-database og samme backupkatalog av begge tjenester.

## 4. Bootstrap første produksjonsdatabase

Legg validert historisk OTEC-CSV i:

```text
/var/lib/otello/raw/
```

Bygg image:

```bash
docker compose build
```

Kjør bootstrap, eksempel med Investing-exporten som allerede er validert i prosjektet:

```bash
docker compose run --rm api python -m app.jobs.bootstrap_production \
  --database /data/otello.db \
  --otec-investing-csv /data/raw/Otello-Corporation-ASA-Stock-Price-History.csv \
  --strict
```

Deretter:

```bash
docker compose run --rm api python -m app.jobs.preflight \
  --database /data/otello.db \
  --strict
```

Start først tjenestene når preflight ender i `READY`:

```bash
docker compose up -d
```

## 5. Nettverk og HTTPS

Web-containeren lytter på `${WEB_PORT}`. Cloud-oppsettet skal plassere HTTPS foran denne porten via providerens load balancer/reverse proxy eller tilsvarende edge.

API-port 8000 skal **ikke** publiseres. Nginx sender `/api/*` internt til `api:8000` på Docker-nettverket.

Anbefalt firewall-prinsipp:

- åpne bare administrasjonstilgang som faktisk trengs;
- eksponer web-porten bare til cloud edge/load balancer når plattformen støtter det;
- ikke eksponer SQLite, scheduler eller FastAPI direkte til internett.

## 6. Scheduler

Produksjonen kjører:

- fast refresh hvert 30. minutt;
- full refresh én gang per døgn;
- verifisert SQLite-backup én gang per døgn.

Jobbresultater lagres i `job_runs`. Se `docs/production-scheduler.md`.

## 7. Backup i cloud

Applikasjonen lager daglige verifiserte SQLite-snapshots i `/data/backups`. Dette beskytter mot logiske/databasefeil, men er **ikke alene en full cloud-backup** dersom hele disken forsvinner.

Produksjonsoppsettet skal derfor i tillegg bruke minst én off-host mekanisme, for eksempel:

- provider-snapshot av persistent disk; eller
- kopi av verifiserte backupfiler til ekstern/object storage.

Automatisk object-storage-opplasting er ikke implementert i repoet ennå. Det bør legges til når endelig cloud-provider er valgt, slik at credentials, retention og restore-prosess kan tilpasses riktig.

## 8. Deploy og oppdatering

Normal oppdatering på cloud-hosten:

```bash
git pull
docker compose build
docker compose up -d
```

Etter større database-/modellendringer:

```bash
docker compose run --rm api python -m app.jobs.preflight \
  --database /data/otello.db \
  --strict
```

## 9. Produksjonskrav

Før cloud-instansen regnes som driftsklar:

1. bootstrap og `preflight --strict` skal være `READY`;
2. web og API skal fungere gjennom HTTPS-endepunktet;
3. `job_runs` skal vise normale fast/full/backup-kjøringer;
4. persistent disk skal overleve restart/redeploy;
5. minst én restore fra en verifisert backup skal testes;
6. off-host backup/snapshot skal være aktivert;
7. secrets skal være utenfor Git.

## GitHub-deploy

CI bygger og validerer produksjonsimage på hver PR. Automatisk deploy fra GitHub Actions er med vilje ikke bundet til én leverandør ennå. Når endelig cloud-provider er valgt, kan deploy-workflow legges til uten å endre applikasjonsarkitekturen.
