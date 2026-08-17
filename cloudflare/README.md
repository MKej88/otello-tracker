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

## Hvorfor Python Worker

Cloudflare støtter FastAPI direkte i Python Workers. Det gjør at NAV-/buyback-/kildevalideringslogikk kan flyttes med minst mulig språkbytte.

Den store endringen er persistence: dagens synkrone `sqlite3`-tilgang må erstattes med et D1 repository/data-access-lag via Worker bindings.

`pyproject.example.toml` viser basisavhengighetene for Worker-runtime. `wrangler.example.jsonc` viser bindings, static assets og cron.

## Kontoressurser som må opprettes

Når Cloudflare-kontoen kobles til prosjektet:

```bash
npx wrangler d1 create otello-nav
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

## Lokal Cloudflare-utvikling – etter Phase 15.1

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
