# Cloudflare production target

Denne katalogen er startpunktet for Cloudflare-native produksjon.

## Valgte tjenester

- **Workers + Static Assets** – React/Vite frontend og API-ruting
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

## Kontoressurser som må opprettes

Når Cloudflare-kontoen kobles til prosjektet:

```bash
npx wrangler d1 create otello-nav
npx wrangler r2 bucket create otello-source-archive
```

Deretter fylles faktiske IDs inn i den endelige `wrangler.jsonc`.

`wrangler.example.jsonc` viser planlagte bindings og cron uten å inneholde konto-ID-er eller secrets.

## Planlagt Worker

Produksjons-Worker skal etter hvert håndtere:

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

## Deploy

Når D1-adapteren er ferdig og parity-testene er grønne:

```bash
npm run build
npx wrangler deploy
```

Endelig GitHub deploy skal bruke Cloudflare Workers Builds eller GitHub Actions med konto-secrets utenfor repoet.
