# Cloudflare production target

Denne katalogen er startpunktet for Cloudflare-native produksjon.

## Valgte tjenester

- **Python Workers + FastAPI** – API og eksisterende Python-forretningslogikk
- **Workers Static Assets** – React/Vite frontend
- **D1** – strukturert produksjonsdatabase
- **R2** – PDF/råkilder/arkiv
- **Cron Triggers** – fast refresh hvert 30. minutt
- **Workflows** – tyngre fullrefresh og retries
- **Workers Secrets / Secrets Store** – secrets

## Ikke produksjonsmål

- Docker Compose som permanent hosting
- Nginx som offentlig origin
- lokal SQLite-fil som autoritativ cloud-database
- SQLite direkte på R2/FUSE

Docker/SQLite beholdes kun som referanse under migreringen.

## Phase 15.1 – D1 schema

Ferdig strukturgrunnlag:

```text
migrations/
  0001_initial_schema.sql   generert fra migrert SQLite-reference
  0002_reference_data.sql  sources + OTEC/BMOB3 identities

tools/
  generate_d1_schema.py    generator + drift-check

wrangler.schema-test.jsonc konto-uavhengig lokal D1-test
```

`0001_initial_schema.sql` redigeres ikke manuelt. Regenerer med:

```bash
python cloudflare/tools/generate_d1_schema.py
```

Kontroller uten å skrive:

```bash
python cloudflare/tools/generate_d1_schema.py --check
```

CI sammenligner D1 mot SQLite-referansen strukturelt og anvender begge migrations i lokal Wrangler D1-runtime. Se `docs/d1-migration.md`.

## Hvorfor Python Worker

FastAPI/Python gjør at NAV-/buyback-/kildevalideringslogikk kan flyttes med minst mulig språkbytte.

Den store endringen er persistence: dagens synkrone `sqlite3`-tilgang erstattes med et D1 repository/data-access-lag via Worker bindings i en senere fase.

`pyproject.example.toml` viser basisavhengighetene for Worker-runtime. `wrangler.example.jsonc` viser bindings, static assets, D1 migrations-katalog og cron.

## Kontoressurser som må opprettes

Når migreringen er klar for remote Cloudflare-ressurser:

```bash
npx wrangler d1 create otello-nav --location=weur
npx wrangler r2 bucket create otello-source-archive
```

Deretter fylles faktiske IDs inn i den endelige `wrangler.jsonc`.

## Planlagt Worker

```text
GET /api/health
GET /api/dashboard/summary
GET /api/dashboard/history
GET /api/buybacks/forecast
...

scheduled */30 * * * *
  -> fast market/news/NAV refresh

scheduled daily / Workflow
  -> full refresh + reconciliation
```

## Lokal Cloudflare-utvikling

Når Worker-entrypoint og D1-adapteren er lagt inn:

```bash
uv run pywrangler dev
```

Deploy:

```bash
npm run build --prefix ../frontend
uv run pywrangler deploy
```

Endelig GitHub deploy skal bruke Cloudflare Workers Builds eller GitHub Actions med konto-secrets utenfor repoet.
