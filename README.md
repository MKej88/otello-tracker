# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med løpende NAV, historisk NAV-rabatt, tilbakekjøp, Bemobi-eksponering, selskapsmeldinger og datakvalitet.

## Status 17.08.2026

Kjernemodellen og live-feedene er implementert og testet. Produksjonsmålet er **Cloudflare-native**.

- **CORE NAV og FULL NAV:** historisk modell + daglig/indikativ live-serie
- **NewsWeb:** historikk, originale buyback-meldinger og daglige transaksjoner
- **Bemobi:** B3 delayed intradag, offisiell daglig CLOSE, CVM og utdelinger/JCP
- **OTEC:** historisk kurs + Euronext delayed + EOD LAST
- **Buyback-prognose:** Safe Harbour/ADV20-basert estimat med historisk validering
- **Phase 14.1–14.3:** lette feeds, sikkerhet og produksjonsytelse
- **Phase 14.5:** Cloudflare-native målarkitektur
- **Phase 15.1:** D1-schema, referansedata og structural parity er CI-validert

Se [PHASE.md](PHASE.md), [docs/cloud-deployment.md](docs/cloud-deployment.md), [docs/d1-migration.md](docs/d1-migration.md) og [docs/production-readiness.md](docs/production-readiness.md).

## Produksjonsarkitektur – Cloudflare

```text
Browser
  |
  v
Cloudflare Python Worker + Static Assets
  |-- FastAPI /api/*
  |-- React/Vite
  |
  +--> D1             strukturert produksjonsdata
  +--> R2             PDF/råkilder/arkiv
  +--> Cron Triggers  30-minutters refresh
  +--> Workflows      tyngre fullrefresh/retries
  +--> Secrets        API-nøkler
```

React/Vite og FastAPI/Python beholdes. Dagens synkrone `sqlite3`-data-access kan ikke brukes som produksjonspersistence i Worker-runtime, så strukturert produksjonsdata flyttes til **Cloudflare D1**.

Docker Compose/Nginx/SQLite beholdes som lokal regresjonsreferanse under migreringen, men er ikke produksjonsmålet.

## Phase 15.1 – D1 schema parity

D1-bootstrapen er nå representert av to migrations:

```text
cloudflare/migrations/
  0001_initial_schema.sql
  0002_reference_data.sql
```

`0001` genereres deterministisk fra sluttilstanden etter alle backend-migreringer. CI feiler hvis den driver fra SQLite-referansen.

Parity-testene verifiserer blant annet:

- samme tabeller og kolonnedefinisjoner;
- samme foreign keys og delete/update-regler;
- samme eksplisitte, unique og partial indekser;
- samme triggere;
- samme stabile sources/instruments;
- tom `PRAGMA foreign_key_check`.

CI anvender også migrations i en ekte **lokal Wrangler D1-runtime**, ikke bare i Python `sqlite3`.

Neste fase er **15.2: historisk SQLite → D1 bootstrap/data parity**.

Detaljer: [docs/d1-migration.md](docs/d1-migration.md).

## NAV-definisjoner

`CORE NAV`:

```text
Bemobi markedsverdi + modellert/rapportert cash
```

`FULL NAV`:

```text
CORE NAV + øvrige nettoeiendeler/-forpliktelser (ONA)
```

Rapportert ONA:

```text
Total assets - cash - Bemobi carrying value - total liabilities
```

Mellom rapporter merkes estimerte/forecast-komponenter eksplisitt. Hvis BMOB3 har fersk dagens pris før OTEC har handlet, kan dagens NAV bruke siste gyldige OTEC-pris og markeres `MIXED`/indikativt.

## Datakilder

- **B3:** BMOB3 delayed + daglig COTAHIST
- **ECB:** BRL/NOK og USD/NOK
- **Euronext:** OTEC delayed/historikk
- **NewsWeb:** Otello-meldinger og buybacks
- **CVM:** Bemobi selskapsmeldinger
- **Otello-rapporter:** kuraterte finansielle ankere
- **MFN:** sekundær fallback/discovery
- **Investing.com CSV:** kun manuell historisk OTEC-fallback

## Cloudflare-lagring

### D1

D1 blir autoritativt produksjonslager for market data, cash, holdings, corporate actions, NAV, buybacks, NewsWeb/CVM-metadata og jobbstatus.

### R2

R2 brukes til større/binære objekter:

- NewsWeb-PDF-er
- rå CSV/ZIP-kilder som skal arkiveres
- historiske importfiler
- eksport/snapshots

R2 brukes ikke som direkte SQLite-filsystem.

## Scheduler på Cloudflare

Fast refresh beholdes logisk hvert 30. minutt, men flyttes til **Cron Triggers**.

Tyngre fullrefresh flyttes til **Workflows/scheduled jobs** med retries per kilde/trinn.

Eksisterende Oslo-/São Paulo-kalenderlogikk skal fortsatt styre hvilke markeder som faktisk er åpne.

## Migreringsplan

1. **Ferdig:** Cloudflare målarkitektur og Worker/D1/R2 scaffold.
2. **Ferdig:** D1-schema + structural parity.
3. **Neste:** verifisert SQLite → D1 bootstrap/import og data parity.
4. D1 repository/data-access-lag.
5. Dashboardets read-only API på Cloudflare.
6. OTEC/BMOB3/NewsWeb-writejobs.
7. Cron Triggers og Workflows.
8. R2 source archive.
9. D1-preflight og datakvalitetskontroll.
10. Auto-deploy fra `main` og custom domain.

Detaljer: [docs/cloud-deployment.md](docs/cloud-deployment.md).

## Lokal utvikling under migreringen

Backend:

```bash
cd backend
pip install -r requirements-dev.txt
python -m pip check
PYTHONPATH=. pytest -q
```

D1-schema/parity:

```bash
python cloudflare/tools/generate_d1_schema.py --check
npx --yes wrangler@4 d1 migrations apply DB --local --config cloudflare/wrangler.schema-test.jsonc
```

Frontend:

```bash
cd frontend
npm ci
npm audit --omit=dev --audit-level=high
npm run build
```

Docker-regresjon:

```bash
docker compose config --quiet
docker compose build api web
docker run --rm --add-host api:127.0.0.1 otello-web:local nginx -t
```

Docker er lokal/reference CI, ikke endelig Cloudflare-produksjonsdeploy.

## Produksjonsdata og secrets

Ikke commit databasefiler, API-nøkler, rå markedsdata eller PDF-er. Cloudflare-secrets skal ligge utenfor Git.

## Neste produksjonsporter

Før Cloudflare-go-live skal:

1. historisk SQLite→D1-import være verifisert;
2. dashboard-API gi samme tall som referanseimplementasjonen;
3. fast/full refresh kjøre gjennom Cron/Workflows;
4. R2 source archive være på plass;
5. D1 preflight/data-health passere;
6. GitHub→Cloudflare deploy være grønn;
7. custom domain/HTTPS fungere;
8. Otello 1H26-ankrene etter 21.08.2026 være importert og avstemt.
