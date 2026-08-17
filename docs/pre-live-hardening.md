# Pre-live hardening

This document is the production gate for the Otello tracker. A fresh clone is **not**
considered production-ready merely because the containers start.

## Phase 13.1 — bootstrap and preflight

A clean database must first be populated with the historical inputs required by the NAV
model. The normal recurring refresh intentionally fetches only recent/current data and is
not a historical bootstrap.

### Clean production bootstrap

Run from the backend container or from `backend/` with `PYTHONPATH=.`:

```bash
python -m app.jobs.bootstrap_production \
  --database /data/otello.db \
  --otec-investing-csv /data/raw/Otello-Corporation-ASA-Stock-Price-History.csv \
  --strict
```

A validated Euronext historical export may be used instead:

```bash
python -m app.jobs.bootstrap_production \
  --database /data/otello.db \
  --otec-csv /data/raw/OTEC.csv \
  --otec-date-order DMY \
  --strict
```

The bootstrap:

1. applies all SQLite migrations;
2. seeds curated Otello/Bemobi facts;
3. fetches ECB BRL/NOK and USD/NOK from 2021-02-10 through the target date;
4. downloads/imports every B3 COTAHIST year from 2021 through the target year;
5. imports supplied historical OTEC prices;
6. runs the normal NewsWeb/CVM/current-market refresh;
7. rebuilds cash, CORE NAV, ONA and FULL NAV;
8. runs the production preflight.

Historical OTEC is deliberately not scraped automatically. A clean bootstrap therefore
needs a validated historical OTEC CSV unless a previously validated production database is
being reused.

### Read-only production gate

After bootstrap, or after copying an existing production database:

```bash
python -m app.jobs.preflight --database /data/otello.db --strict
```

`READY` requires, among other things:

- SQLite integrity and latest migration;
- all required core tables and curated report facts;
- OTEC/BMOB3 history back to the Bemobi IPO period;
- historical BRL/NOK and USD/NOK;
- an actual FX rate within seven days before every non-NOK reported cash anchor;
- recent OTEC, BMOB3 and FX inputs;
- NewsWeb archive and daily buyback data;
- populated daily cash, CORE NAV, ONA and FULL NAV layers;
- a dashboard that can produce a NAV snapshot.

`DEGRADED`/`ESTIMATED` current NAV quality is reported as a warning rather than a bootstrap
failure when all required source data exists. Between reports this can be legitimate because
cash and ONA are explicitly marked as forecast/interpolated rather than presented as reported
facts.

## Remaining pre-live phases

- Phase 13.2: split fast/slow refresh cadence, incremental collectors, job observability and backups.
- Phase 13.3: component freshness/timestamps, frontend auto-refresh and Bemobi ownership display.
- Phase 13.4: clean Docker integration smoke, dependency locking, explicit Europe/Oslo timezone and documentation sync.
- After Otello 1H26: import the new report anchors and reconcile current cash/ONA before declaring the model fully report-anchored.
