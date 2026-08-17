# Otello NAV Dashboard

Privat investeringsdashboard for Otello/Bemobi med løpende NAV, historisk NAV-rabatt, tilbakekjøp, Bemobi-eksponering, selskapsmeldinger og datakvalitet.

## Status 17.08.2026

Kjernemodellen, pre-live-plattformen og de lette live-feedene er implementert:

- **CORE NAV og FULL NAV:** historisk modell + daglig/indikativ live-serie
- **NewsWeb:** historikk, originale buyback-meldinger og daglige transaksjoner
- **Bemobi:** lett B3 delayed intradag, offisiell daglig CLOSE, CVM-nyheter og skattejusterte utdelinger/JCP
- **OTEC:** historisk kurs + lette Euronext delayed-vinduer + EOD LAST
- **Buyback-prognose:** Safe Harbour/ADV20-basert estimat med historisk validering
- **Phase 13:** produksjons-bootstrap, preflight, scheduler/backup, freshness og reproducerbar CI
- **Phase 14.1:** lett OTEC-feed med gap recovery og EOD-finalisering
- **Phase 14.2:** lett BMOB3-feed med delayed LAST og liten offisiell daglig COTAHIST CLOSE
- **Phase 14.3:** sikkerhet/Pi-ytelse, dirty-state for cash/seeds, inkrementelle tunge kilder og mixed-date live NAV

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

Nginx har API-rate limiting, korte proxy-timeouts og sikkerhetsheadere/CSP. Compose-tjenestene kjører med `no-new-privileges`. Alle produksjonstjenester bruker eksplisitt `Europe/Oslo`.

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

Live-modellen bruker samme NAV-formel og samme validerte lookbacks. Dersom BMOB3 har en fersk dagens pris før OTEC har handlet, kan dagens NAV derfor bruke siste gyldige OTEC-pris sammen med dagens BMOB3. Dashboardet viser da komponentdatoene og markerer snapshotet `MIXED`/indikativt i stedet for å late som markedene er synkroniserte.

## Viktigste datakilder

- **B3:** offentlig 15-minutters delayed BMOB3 intradag + offisiell daglig COTAHIST CLOSE/historikk
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

- OTEC `LAST_15_MINUTES` / `LAST_HOUR`, med gap recovery bare ved behov
- BMOB3 liten delayed quote og separat EOD-logikk
- inkrementell NewsWeb-historikk og buybacks
- buyback cash/programdata
- cash-rebuild **bare når modellinput eller datohorisont faktisk er endret**
- siste relevante CORE/FULL snapshot; dagens indikative snapshot kan bygges når ett av markedene har fersk dagens handel

Fastløpet laster **ikke** ned hele B3-år, ECB-historikk, CVM-årsarkiver eller MFN-fallback hver halvtime. Kuraterte statiske manifests skrives heller ikke på nytt når fingerprinten er uendret.

### Full refresh – standard én gang per døgn

Tar tyngre kilder og avstemminger. NewsWeb-buybacks bruker automatisk sikkerhetsoverlapp fra siste kjente data i stedet for å starte i 2023 hver dag. CVM inneværende år er løpende; foregående år kontrolleres periodisk for korreksjoner i stedet for å lastes ned daglig. Fullrefresh primer cash dirty-state slik at neste fastsyklus ikke gjentar samme fullrebuild. Jobbstatus lagres i `job_runs`.

### Backup – standard én gang per døgn

SQLite sin backup-API brukes mot den levende WAL-databasen, og snapshotet må passere `PRAGMA integrity_check`. Backuper lagres som standard i `/data/backups`.

Automatisk sletting/retention er foreløpig **ikke** aktivert. Diskforbruket må overvåkes og en sikker rotasjon/restore-test skal gjøres som del av faktisk Pi-drift.

## Datakvalitet og kildevern

Siste NAV-snapshot får en separat timestamp-status:

- `ALIGNED` – OTEC, BMOB3 og BRL/NOK har kompatibel markedsdato
- `MIXED` – gyldige inputs, men fra ulike markedsdatoer; NAV er indikativ
- `STALE` – minst én markedsinput er for gammel
- `UNKNOWN` – manglende timestamp-metadata

GUI-et oppdaterer seg automatisk hvert 2. minutt og viser inputdatoene.

En gammel rapportert Bemobi-eierprosent vises ikke som om den var dagens prosent. NAV bruker det verifiserte antallet Bemobi-aksjer; prosent vises først når et oppdatert BMOB3-utestående aksjetall er verifisert.

Endrende OTEC delayed-filer får immutabel payload-identitet, slik at en eldre markedspris aldri peker på hash/metadata fra en senere nedlasting. NewsWeb JSON/PDF har eksplisitte responsgrenser før parsing.

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

CI kjører backendtester/dependency-konsistens, låst frontend-build + produksjonsdependency-audit og faktisk produksjons-Docker/Nginx-validering på hver PR.

## Secrets og produksjonsdata

Ikke commit `.env`, databasefiler, API-nøkler, rå markedsdata eller NewsWeb-PDF-er. Produksjonsdata ligger utenfor Git-historikken.

## Før endelig live-erklæring

Kodebasen kan preflightes nå, men to operative/finansielle steg står igjen:

1. Kjør bootstrap + `preflight --strict` mot den **faktiske** produksjonsdatabasen på Pi-en.
2. Importer og avstem Otello 1H26 når rapporten publiseres 21.08.2026, slik at dagens forecast-partial cash/ONA erstattes med nye rapportankre.

I tillegg skal backup-restore testes på Pi-en før systemet betraktes som fullt driftsklart. Automatisk backup-retention aktiveres først når den restore-rutinen er etablert.
