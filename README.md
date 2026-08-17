# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med løpende NAV, historisk NAV-rabatt, tilbakekjøp, Bemobi-eksponering, selskapsmeldinger og datakvalitet.

## Status 17.08.2026

Kjernemodellen og pre-live hardening er implementert:

- **CORE NAV og FULL NAV:** historisk modell + daglig serie
- **NewsWeb:** historikk, originale buyback-meldinger og daglige transaksjoner
- **Bemobi:** B3-priser, CVM-nyheter og skattejusterte utdelinger/JCP
- **OTEC:** historisk kurs + Euronext delayed LAST
- **Buyback-prognose:** Safe Harbour/ADV20-basert estimat med historisk validering
- **Phase 13.1:** ren produksjons-bootstrap + streng preflight
- **Phase 13.2:** lett 30-minutters refresh, daglig fullrefresh, jobbstatus og verifiserte SQLite-backuper
- **Phase 13.3:** OTEC/BMOB3/FX-datoferskhet, automatisk GUI-refresh og vern mot gammel Bemobi-eierandel
- **Phase 13.4:** dependency-lock, Europe/Oslo-tid og produksjons-Docker-build i CI

Se [PHASE.md](PHASE.md) for gjeldende plan og [docs/pre-live-hardening.md](docs/pre-live-hardening.md) for produksjonsporten.

## Arkitektur

```text
Browser
  |
  v
Nginx / React
  |
  | /api/*
  v
FastAPI  ---- scheduler
  |             |-- fast refresh hvert 30. min
  |             |-- full refresh daglig
  |             `-- SQLite backup daglig
  v
SQLite /data/otello.db
```

FastAPI-porten publiseres ikke direkte til hosten. Web bindes som standard til `127.0.0.1:3000`, slik at en senere Cloudflare Tunnel/Access kan være eneste eksterne inngang.

Alle produksjonstjenester bruker eksplisitt `Europe/Oslo`.

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

FULL og CORE lagres som separate serier. Dashboardet foretrekker bare FULL når FULL er oppdatert til samme dato som CORE. Mellom rapporter merkes estimerte/forecast-komponenter eksplisitt; de presenteres ikke som rapporterte tall.

## Viktigste datakilder

- **B3 COTAHIST:** offisiell BMOB3 EOD-historikk
- **ECB:** BRL/NOK og USD/NOK
- **Euronext:** OTEC delayed-pris og historisk markedsdata
- **Oslo Børs NewsWeb:** offisielle Otello-meldinger og buyback-vedlegg
- **CVM:** Bemobi selskapsmeldinger
- **Otello-rapporter:** kuraterte finansielle ankere
- **MFN:** sekundær fallback/discovery, aldri autoritativ over offisielle kilder
- **Investing.com CSV:** kun manuell historisk OTEC-fallback; ingen automatisert scraping

## Produksjonsoppstart – viktig

En ny database er **ikke** klar bare fordi Docker-containerne starter. Før første live-start skal historiske data bootstrapes og preflight passere.

På Raspberry Pi/Linux eller annen Docker-host:

```bash
cp .env.example .env
mkdir -p data/raw data/backups
docker compose build
```

Legg den validerte historiske OTEC-filen under `data/raw/`. Deretter, eksempel med Investing-exporten som allerede er brukt i prosjektet:

```bash
docker compose run --rm api python -m app.jobs.bootstrap_production \
  --database /data/otello.db \
  --otec-investing-csv /data/raw/Otello-Corporation-ASA-Stock-Price-History.csv \
  --strict
```

Kjør deretter produksjonsporten eksplisitt:

```bash
docker compose run --rm api python -m app.jobs.preflight \
  --database /data/otello.db \
  --strict
```

Bare når den ender i `READY`:

```bash
docker compose up -d
```

Dashboardet ligger lokalt på:

```text
http://localhost:3000
```

Detaljene for alle readiness-kontroller står i [docs/pre-live-hardening.md](docs/pre-live-hardening.md).

## Scheduler og ytelse

Produksjonsscheduler har to nivåer:

### Fast refresh – standard hvert 30. minutt

- Euronext delayed OTEC
- inkrementell NewsWeb-historikk
- inkrementelle buybacks
- buyback cash/programdata
- daglig cash
- siste relevante CORE/FULL NAV-snapshot

Den laster **ikke** ned hele B3-år, ECB-historikk, CVM-arkiver eller MFN-fallback hver halvtime.

### Full refresh – standard én gang per døgn

Tar de tyngre kildene, avstemminger og full historisk rebuild. Jobbstatus lagres i `job_runs`.

### Backup – standard én gang per døgn

SQLite sin backup-API brukes mot den levende WAL-databasen, og snapshotet må passere `PRAGMA integrity_check`. Backuper lagres som standard i `/data/backups`.

Automatisk sletting/retention er foreløpig **ikke** aktivert. Diskforbruket må overvåkes og en sikker rotasjon/restore-test skal gjøres som del av faktisk Pi-drift.

## Dashboardets datoferskhet

Siste NAV-snapshot får en separat timestamp-status:

- `ALIGNED` – OTEC, BMOB3 og BRL/NOK har kompatibel markedsdato
- `MIXED` – gyldige inputs, men fra ulike markedsdatoer; NAV er indikativ
- `STALE` – minst én markedsinput er for gammel
- `UNKNOWN` – manglende timestamp-metadata

GUI-et oppdaterer seg automatisk hvert 2. minutt og viser inputdatoene.

En gammel rapportert Bemobi-eierprosent vises ikke som om den var dagens prosent. NAV bruker det verifiserte antallet Bemobi-aksjer; prosent vises først når et oppdatert BMOB3-utestående aksjetall er verifisert.

## Utvikling

Backend:

```bash
cd backend
pip install -r requirements-dev.txt
PYTHONPATH=. pytest -q
```

Frontend:

```bash
cd frontend
npm ci
npm run build
```

Docker/produksjonsimage:

```bash
docker compose config --quiet
docker compose build api web
```

CI kjører alle tre kontrollene på hver PR. Frontend bruker `package-lock.json`; direkte Python-avhengigheter er pinnet til testede versjoner.

## Secrets og produksjonsdata

Ikke commit `.env`, databasefiler, API-nøkler, rå markedsdata eller NewsWeb-PDF-er. Produksjonsdata ligger utenfor Git-historikken.

## Før endelig live-erklæring

Kodebasen kan preflightes nå, men to operative/finansielle steg står igjen:

1. Kjør bootstrap + `preflight --strict` mot den **faktiske** produksjonsdatabasen på Pi-en.
2. Importer og avstem Otello 1H26 når rapporten publiseres 21.08.2026, slik at dagens forecast-partial cash/ONA erstattes med nye rapportankre.

I tillegg bør backup-restore testes på Pi-en før systemet betraktes som fullt driftsklart.
