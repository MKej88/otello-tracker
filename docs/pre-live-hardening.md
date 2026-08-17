# Pre-live hardening

Dette dokumentet er produksjonsporten for Otello-trackeren. En fresh clone er **ikke** produksjonsklar bare fordi containerne starter.

## 1. Ren produksjons-bootstrap

Kjør fra backend-containeren eller fra `backend/` med `PYTHONPATH=.`:

```bash
python -m app.jobs.bootstrap_production \
  --database /data/otello.db \
  --otec-investing-csv /data/raw/Otello-Corporation-ASA-Stock-Price-History.csv \
  --strict
```

En validert Euronext-CSV kan brukes i stedet:

```bash
python -m app.jobs.bootstrap_production \
  --database /data/otello.db \
  --otec-csv /data/raw/OTEC.csv \
  --otec-date-order DMY \
  --strict
```

Bootstrapen:

1. kjører alle SQLite-migreringer;
2. seeder kuraterte Otello/Bemobi-fakta;
3. henter ECB BRL/NOK og USD/NOK fra 10.02.2021 til måldato;
4. importerer alle B3 COTAHIST-år fra 2021 til måldatoens år;
5. importerer historisk OTEC fra den oppgitte validerte filen;
6. kjører NewsWeb/CVM/current-market refresh;
7. bygger cash, CORE NAV, ONA og FULL NAV;
8. avslutter med production preflight.

Historisk OTEC scrapes ikke automatisk. En ren bootstrap trenger derfor validert historisk OTEC-CSV, med mindre en allerede validert produksjonsdatabase gjenbrukes.

## 2. Read-only produksjonsport

Etter bootstrap, eller etter kopiering av en eksisterende produksjonsdatabase:

```bash
python -m app.jobs.preflight --database /data/otello.db --strict
```

`READY` krever blant annet:

- SQLite `integrity_check` og siste migrering;
- nødvendige tabeller og kuraterte rapportfakta;
- OTEC/BMOB3-historikk tilbake til Bemobi IPO-perioden;
- historisk BRL/NOK og USD/NOK;
- faktisk FX-rate innen syv dager før hvert rapporterte ikke-NOK cash-anker;
- fersk OTEC, BMOB3 og FX;
- NewsWeb-arkiv og daglige buyback-data;
- daglig cash, CORE NAV, ONA og FULL NAV;
- et dashboard som kan produsere et gyldig NAV-snapshot.

`DEGRADED`/`ESTIMATED` kan være et varsel i stedet for bootstrap-feil når alle nødvendige kildedata finnes. Mellom rapporter kan cash/ONA legitimt være forecast/interpolert, men skal aldri presenteres som rapporterte fakta.

## 3. Scheduler og ytelse

Produksjon bruker to refreshnivåer:

### Fast refresh

Standard: hvert 30. minutt.

- Euronext delayed OTEC
- inkrementell NewsWeb
- inkrementelle buybacks
- buyback cash/programdata
- daglig cash
- siste relevante NAV-snapshot

Fastløpet skal ikke laste hele B3-år, ECB-historikk, CVM-arkiver eller MFN-fallback.

### Full refresh

Standard: én gang per døgn. Tar tyngre kilder, full historisk rebuild og avstemminger.

Alle fast/full/backup-kjøringer lagres i `job_runs`.

## 4. Backup

Standard: én verifisert SQLite-snapshot per døgn til `/data/backups`.

Backupen bruker SQLite backup-API mot den levende WAL-databasen og må passere:

```sql
PRAGMA integrity_check;
```

før snapshotet godtas.

**Kjent driftsoppgave:** automatisk retention/sletting er ikke aktivert. På Pi-en skal diskforbruk overvåkes, og minst én faktisk restore-test gjennomføres før full driftsklar-erklæring.

## 5. Datoferskhet i NAV

Dashboard-API og GUI viser kompatibiliteten mellom OTEC-, BMOB3- og BRL/NOK-datoene:

- `ALIGNED`
- `MIXED`
- `STALE`
- `UNKNOWN`

`MIXED` betyr at inputene kan være gyldige, men fra ulike markedsdatoer. NAV-et er da indikativt. Selve verdsettelsesformelen endres ikke.

GUI-et henter nye data automatisk hvert 2. minutt.

En gammel rapportert Bemobi-eierprosent eksponeres ikke som dagens eierandel. NAV bruker det verifiserte Bemobi-aksjeantallet.

## 6. Reproducerbar produksjon

- frontend direkte avhengigheter er pinnet;
- `package-lock.json` låser npm-grafen;
- Docker og CI bruker `npm ci`;
- backend direkte Python-avhengigheter er pinnet til versjoner som passerte CI;
- backend/scheduler bruker eksplisitt `Europe/Oslo`;
- produksjonsimage inkluderer timezone-data;
- CI validerer Compose **og bygger faktiske backend/frontend Docker-images**.

## 7. Faktisk Pi-gate

Når Raspberry Pi-en er tilgjengelig:

```bash
cp .env.example .env
mkdir -p data/raw data/backups
docker compose build
```

Kjør bootstrap, deretter:

```bash
docker compose run --rm api python -m app.jobs.preflight \
  --database /data/otello.db \
  --strict
```

Kun ved `READY`:

```bash
docker compose up -d
```

Før systemet kalles fullt driftsklart:

1. kontroller scheduler/job_runs gjennom minst ett døgn;
2. bekreft at daglig backup blir opprettet og er integritetsvalidert;
3. gjør en faktisk restore-test;
4. bekreft at web/API bare eksponeres gjennom ønsket lokal/Cloudflare-tilgang.

## 8. Otello 1H26 – neste finansielle gate

Etter rapporten 21.08.2026:

1. importer nye rapporterte cash-/balanseankre;
2. avstem ONA;
3. rebuild CORE/FULL;
4. kontroller residualer og aksjetall;
5. kjør `preflight --strict` på nytt.

Før dette kan dagens cash/ONA legitimt være `FORECAST_PARTIAL`/estimert. Dashboardet skal vise denne kvalitetsstatusen tydelig.
