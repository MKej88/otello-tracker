# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med løpende NAV, historisk NAV-rabatt, tilbakekjøp, Bemobi-eksponering, selskapsmeldinger og datakvalitet.

## Status 17.08.2026

Kjernemodellen, produksjonsplattformen og de lette live-feedene er implementert:

- **CORE NAV og FULL NAV:** historisk modell + daglig/indikativ live-serie
- **NewsWeb:** historikk, originale buyback-meldinger og daglige transaksjoner
- **Bemobi:** lett B3 delayed intradag, offisiell daglig CLOSE, CVM-nyheter og skattejusterte utdelinger/JCP
- **OTEC:** historisk kurs + lette Euronext delayed-vinduer + EOD LAST
- **Buyback-prognose:** Safe Harbour/ADV20-basert estimat med historisk validering
- **Phase 13:** produksjons-bootstrap, preflight, scheduler/backup, freshness og reproducerbar CI
- **Phase 14.1:** lett OTEC-feed med gap recovery og EOD-finalisering
- **Phase 14.2:** lett BMOB3-feed med delayed LAST og liten offisiell daglig COTAHIST CLOSE
- **Phase 14.3:** sikkerhet/ytelse, dirty-state for cash/seeds, inkrementelle tunge kilder og mixed-date live NAV
- **Phase 14.4:** cloud-first deployoppsett med persistent lagring og produksjonsrunbook

Se [PHASE.md](PHASE.md), [docs/cloud-deployment.md](docs/cloud-deployment.md) og [docs/production-readiness.md](docs/production-readiness.md).

## Cloud-arkitektur

```text
Internet
  |
  v
Cloud edge / HTTPS reverse proxy
  |
  v
Nginx / React (web)
  |
  | /api/* på privat Docker-nett
  v
FastAPI  ---- scheduler
  |             |-- fast refresh hvert 30. min
  |             |-- full refresh daglig
  |             `-- SQLite backup daglig
  v
Persistent cloud disk: /data/otello.db
```

Bare `web` skal eksponeres eksternt. FastAPI kjører på privat Docker-nett og proxes via Nginx. Nginx har API-rate limiting, proxy-timeouts og sikkerhetsheadere/CSP. Compose-tjenestene kjører med `no-new-privileges`, og produksjon bruker eksplisitt `Europe/Oslo`.

Så lenge SQLite brukes er produksjonsmodellen **én aktiv app-host/region** med API og scheduler mot samme persistente disk. Horisontal skalering over flere verter krever først en annen databasearkitektur.

## NAV-definisjoner

`CORE NAV`:

```text
Bemobi markedsverdi + modellert/rapportert cash
```

`FULL NAV`:

```text
CORE NAV + øvrige nettoeiendeler/-forpliktelser (ONA)
```

Rapportert ONA beregnes fra Otellos konsoliderte balanse som:

```text
Total assets - cash - Bemobi carrying value - total liabilities
```

FULL og CORE lagres som separate serier. Mellom rapporter merkes estimerte/forecast-komponenter eksplisitt; de presenteres ikke som rapporterte tall.

Live-modellen bruker samme NAV-formel og samme validerte lookbacks. Dersom BMOB3 har fersk dagens pris før OTEC har handlet, kan dagens NAV bruke siste gyldige OTEC-pris sammen med dagens BMOB3. Dashboardet viser da komponentdatoene og markerer snapshotet `MIXED`/indikativt.

## Viktigste datakilder

- **B3:** offentlig 15-minutters delayed BMOB3 intradag + offisiell daglig COTAHIST CLOSE/historikk
- **ECB:** BRL/NOK og USD/NOK
- **Euronext:** OTEC delayed-pris og historisk markedsdata
- **Oslo Børs NewsWeb:** offisielle Otello-meldinger og buyback-vedlegg
- **CVM:** Bemobi selskapsmeldinger
- **Otello-rapporter:** kuraterte finansielle ankere
- **MFN:** sekundær fallback/discovery, aldri autoritativ over offisielle kilder
- **Investing.com CSV:** kun manuell historisk OTEC-fallback; ingen automatisert scraping

## Produksjonsoppsett i cloud

Repoet er provider-nøytralt. Standardoppsettet er en Linux cloud-host/container-host med Docker Compose og persistent disk.

Start med produksjonsmalen:

```bash
cp .env.production.example .env
```

Sett minst endelig HTTPS-origin og persistent host-katalog:

```env
APP_ENV=production
WEB_BIND=0.0.0.0
WEB_PORT=3000
DATA_DIR=/var/lib/otello
DATABASE_PATH=/data/otello.db
CORS_ORIGINS=https://dashboard.example.com
TZ=Europe/Oslo
```

Legg validert historisk OTEC-CSV i `${DATA_DIR}/raw/`, bygg image og bootstrap databasen:

```bash
docker compose build

docker compose run --rm api python -m app.jobs.bootstrap_production \
  --database /data/otello.db \
  --otec-investing-csv /data/raw/Otello-Corporation-ASA-Stock-Price-History.csv \
  --strict
```

Kjør produksjonsporten:

```bash
docker compose run --rm api python -m app.jobs.preflight \
  --database /data/otello.db \
  --strict
```

Bare ved `READY`:

```bash
docker compose up -d
```

HTTPS skal termineres hos cloud-provider, load balancer eller annen reverse proxy/edge foran web-porten. API-port 8000 skal ikke publiseres.

Detaljert oppsett står i [docs/cloud-deployment.md](docs/cloud-deployment.md).

## Scheduler og ytelse

### Fast refresh – standard hvert 30. minutt

- OTEC `LAST_15_MINUTES` / `LAST_HOUR`, med gap recovery bare ved behov
- BMOB3 liten delayed quote og separat EOD-logikk
- inkrementell NewsWeb-historikk og buybacks
- buyback cash/programdata
- cash-rebuild bare når modellinput eller datohorisont faktisk er endret
- siste relevante CORE/FULL snapshot

Fastløpet laster ikke ned hele B3-år, ECB-historikk, CVM-årsarkiver eller MFN-fallback hver halvtime. Kuraterte statiske manifests skrives heller ikke på nytt når fingerprinten er uendret.

### Full refresh – standard én gang per døgn

Tar tyngre kilder og avstemminger. NewsWeb-buybacks bruker sikkerhetsoverlapp fra siste kjente data. CVM inneværende år er løpende; foregående år kontrolleres periodisk. Fullrefresh primer cash dirty-state slik at neste fastsyklus ikke gjentar samme fullrebuild. Jobbstatus lagres i `job_runs`.

### Backup – standard én gang per døgn

SQLite backup-API brukes mot den levende WAL-databasen, og snapshotet må passere `PRAGMA integrity_check`. Backuper lagres i `/data/backups`.

I cloud skal dette kombineres med **off-host backup**, for eksempel provider-snapshot eller object storage. Automatisk object-storage-opplasting legges til når endelig cloud-provider er valgt.

## Datakvalitet og kildevern

Siste NAV-snapshot får timestamp-status:

- `ALIGNED` – OTEC, BMOB3 og BRL/NOK har kompatibel markedsdato
- `MIXED` – gyldige inputs, men fra ulike markedsdatoer; NAV er indikativ
- `STALE` – minst én markedsinput er for gammel
- `UNKNOWN` – manglende timestamp-metadata

GUI-et oppdaterer seg automatisk hvert 2. minutt og viser inputdatoene.

En gammel rapportert Bemobi-eierprosent vises ikke som dagens prosent. NAV bruker det verifiserte antallet Bemobi-aksjer. Endrende OTEC delayed-filer får immutabel payload-identitet, og NewsWeb JSON/PDF har eksplisitte responsgrenser før parsing.

## Utvikling og CI

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

Docker/produksjonsimage:

```bash
docker compose config --quiet
docker compose build api web
docker run --rm --add-host api:127.0.0.1 otello-web:local nginx -t
```

CI kjører backendtester/dependency-konsistens, låst frontend-build + produksjonsdependency-audit og produksjons-Docker/Nginx-validering på hver PR.

## Secrets og produksjonsdata

Ikke commit `.env`, databasefiler, API-nøkler, rå markedsdata eller NewsWeb-PDF-er. Ekte secrets skal ligge i cloud-providerens secret store eller hostens `.env`.

## Før endelig live-erklæring

Produksjonen er klar når:

1. persistent cloud storage er montert og overlever redeploy;
2. bootstrap + `preflight --strict` er `READY` på produksjonsdatabasen;
3. HTTPS-endepunktet fungerer og bare web er eksponert;
4. scheduler/job_runs og daglig backup er verifisert;
5. restore fra backup er testet;
6. off-host backup/snapshot er aktivert;
7. Otello 1H26-ankrene etter 21.08.2026 er importert og avstemt.
