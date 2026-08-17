# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med løpende NAV, historisk NAV-rabatt, tilbakekjøp, Bemobi-eksponering, selskapsmeldinger og datakvalitet.

## Status 17.08.2026

Kjernemodellen og live-feedene er implementert og testet. Produksjonsmålet er nå **Cloudflare-native**, ikke en generell cloud-VM/container-host.

- **CORE NAV og FULL NAV:** historisk modell + daglig/indikativ live-serie
- **NewsWeb:** historikk, originale buyback-meldinger og daglige transaksjoner
- **Bemobi:** B3 delayed intradag, offisiell daglig CLOSE, CVM og utdelinger/JCP
- **OTEC:** historisk kurs + Euronext delayed + EOD LAST
- **Buyback-prognose:** Safe Harbour/ADV20-basert estimat med historisk validering
- **Phase 14.1–14.3:** lette feeds, sikkerhet og produksjonsytelse
- **Phase 14.4:** generisk cloud-grunnlag
- **Phase 14.5:** Cloudflare-native målarkitektur og migreringsplan

Se [PHASE.md](PHASE.md), [docs/cloud-deployment.md](docs/cloud-deployment.md) og [docs/production-readiness.md](docs/production-readiness.md).

## Produksjonsarkitektur – Cloudflare

```text
Browser
  |
  v
Cloudflare Worker + Static Assets
  |-- React/Vite
  |-- /api/*
  |
  +--> D1             strukturert produksjonsdata
  +--> R2             PDF/råkilder/arkiv
  +--> Cron Triggers  30-minutters refresh
  +--> Workflows      tyngre fullrefresh/retries
  +--> Secrets        API-nøkler
```

React/Vite beholdes. FastAPI/Python kan fortsatt brukes i Workers, men dagens backend kan ikke deployes uendret fordi den bruker lokal `sqlite3`-fil. Produksjonsdata skal derfor migreres til **Cloudflare D1**.

Cloudflare Containers er ikke valgt som primær databasearkitektur fordi containerdisk er ephemeral. Docker Compose/Nginx beholdes foreløpig for lokal regresjonstesting under migreringen, men er ikke produksjonsmålet.

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

Eksisterende SQLite-schema skal porteres uten å endre den finansielle semantikken.

### R2

R2 brukes til større/binære objekter:

- NewsWeb-PDF-er
- rå CSV/ZIP-kilder som skal arkiveres
- historiske importfiler
- eksport/snapshots

R2 skal ikke brukes som direkte SQLite-filsystem.

## Scheduler på Cloudflare

Fast refresh beholdes logisk hvert 30. minutt, men flyttes fra langlevende Docker-scheduler til **Cron Triggers**.

Tyngre fullrefresh flyttes til **Workflows/scheduled jobs** med retries per kilde/trinn.

Cloudflare Cron kjører i UTC, så eksisterende Oslo-/São Paulo-kalenderlogikk skal fortsatt styre hvilke markeder som faktisk er åpne.

## Kostnadsnivå

Migreringen bygges Cloudflare-native, men produksjonsmålet er i utgangspunktet **Workers Paid**. Bakgrunnen er at Free-planens CPU-grense per Worker/Cron-invokasjon er svært lav sammenlignet med våre CSV/PDF-/modelljobber.

D1 og Worker-arkitekturen skal likevel holdes effektiv nok til at faktisk bruk/kostnad blir liten.

## Migreringsplan

1. Workers/Static Assets-oppsett for eksisterende React-app.
2. D1-migrations basert på dagens SQLite-schema.
3. Verifisert SQLite → D1 bootstrap/import.
4. D1 data-access-lag.
5. Dashboardets read-only API på Cloudflare.
6. OTEC/BMOB3/NewsWeb-writejobs.
7. Cron Triggers og Workflows.
8. R2 source archive.
9. D1-preflight og datakvalitetskontroll.
10. Auto-deploy fra `main` og custom domain.

Detaljer: [docs/cloud-deployment.md](docs/cloud-deployment.md).

## Lokal utvikling under migreringen

Den eksisterende implementasjonen kan fortsatt testes lokalt:

Backend:

```bash
cd backend
pip install -r requirements-dev.txt
python -m pip check
PYTHONPATH=. pytest -q
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

Dette er lokal/reference CI, ikke endelig Cloudflare-produksjonsdeploy.

## Produksjonsdata og secrets

Ikke commit databasefiler, API-nøkler, rå markedsdata eller PDF-er. Cloudflare-secrets skal legges i Workers Secrets/Secrets Store, ikke i Git.

## Neste produksjonsporter

Før Cloudflare-go-live skal:

1. D1-schema og SQLite→D1-import være verifisert;
2. dashboard-API gi samme tall som dagens referanseimplementasjon;
3. fast/full refresh kjøre gjennom Cron/Workflows;
4. R2 source archive være på plass;
5. D1 preflight/data-health passere;
6. GitHub→Cloudflare deploy være grønn;
7. custom domain/HTTPS fungere;
8. Otello 1H26-ankrene etter 21.08.2026 være importert og avstemt.
