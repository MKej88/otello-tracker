# Phase 15.7 – Cloudflare go-live

This runbook turns the CI-validated Cloudflare implementation into the remote production system. Repository code can be prepared without account access; resource creation, secrets and the first deploy require access to the target Cloudflare account.

## 1. Plan requirement

Use **Workers Paid** for production.

The application contains Python Workflows that parse NewsWeb PDFs and create a deterministic D1 logical snapshot. Workers Free/Workflows Free has only a 10 ms CPU allowance, which is not a credible production envelope for those steps. Production config therefore renders a guarded paid-plan limit of:

```json
{
  "limits": {
    "cpu_ms": 60000,
    "subrequests": 2000
  }
}
```

This is a maximum allowance, not a target. After remote deployment, inspect real CPU time in Workers Logs and reduce the cap if practical.

## 2. Create account resources

From `cloudflare/` after authenticating Wrangler:

```bash
npx wrangler d1 create otello-nav --location=weur
npx wrangler r2 bucket create otello-source-archive
```

Record the D1 database ID returned by Cloudflare. Do not commit account tokens or the rendered production config.

## 3. Take the cutover snapshot from the validated SQLite reference

Run the existing preflight first against the concrete SQLite reference database that will be used for cutover:

```bash
cd backend
PYTHONPATH=. python -m app.jobs.preflight --database ../data/otello.db --strict
cd ..
```

Then export the deterministic D1 package:

```bash
python cloudflare/tools/d1_bootstrap.py export \
  --database data/otello.db \
  --sql data/d1-bootstrap/otello-production.sql \
  --manifest data/d1-bootstrap/otello-production.manifest.json
```

The real database path may differ. Use the actual validated reference file; never substitute the CI fixture for production data.

## 4. Render production configuration

Set environment values locally:

```text
CLOUDFLARE_D1_DATABASE_ID=<actual D1 UUID>
CLOUDFLARE_WORKER_NAME=otello-tracker
CLOUDFLARE_D1_DATABASE_NAME=otello-nav
CLOUDFLARE_R2_BUCKET_NAME=otello-source-archive
CLOUDFLARE_CUSTOM_DOMAIN=<optional hostname only>
```

Render:

```bash
python cloudflare/tools/render_production_config.py
```

The generated `cloudflare/wrangler.production.jsonc` is gitignored. It enables Workers Logs, uses the real D1/R2 bindings, and configures a Custom Domain only when a hostname is supplied. Without a custom domain, the first deployment can use `workers.dev`.

## 5. Apply schema and import the production snapshot

```bash
cd cloudflare
npx wrangler d1 migrations apply DB --remote --config wrangler.production.jsonc
npx wrangler d1 execute DB --remote --config wrangler.production.jsonc \
  --file ../data/d1-bootstrap/otello-production.sql
```

Do this before turning on automatic production deployment. Keep the bootstrap SQL/manifest outside Git.

## 6. Configure GitHub production secrets and variables

Create a GitHub `production` environment and add these **secrets**:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_D1_DATABASE_ID
```

The API token should be scoped only to the Cloudflare account/zone needed for this Worker.

Add these repository/environment **variables**:

```text
CLOUDFLARE_WORKER_NAME=otello-tracker
CLOUDFLARE_D1_DATABASE_NAME=otello-nav
CLOUDFLARE_R2_BUCKET_NAME=otello-source-archive
CLOUDFLARE_CUSTOM_DOMAIN=             # optional at first
CLOUDFLARE_PUBLIC_URL=https://...     # used for HTTP preflight
CLOUDFLARE_DEPLOY_ENABLED=false
```

`.github/workflows/deploy-cloudflare.yml` can always be started manually. Push-to-main deploys remain skipped until `CLOUDFLARE_DEPLOY_ENABLED=true`.

## 7. First deploy

Run **Deploy Cloudflare production** manually in GitHub Actions.

The workflow:

1. builds the frontend;
2. renders production Wrangler config;
3. applies remote D1 migrations;
4. deploys the Python Worker + Workflow using `pywrangler`;
5. calls `/api/health` and `/api/dashboard/summary` when `CLOUDFLARE_PUBLIC_URL` is configured;
6. fails if the API is not healthy or the dashboard is not ready.

Only after this succeeds should `CLOUDFLARE_DEPLOY_ENABLED` be changed to `true` for automatic deployment on `main`.

## 8. Custom domain / HTTPS

For this project the Worker is the application origin, so a Cloudflare **Custom Domain** is the intended production routing mode. Set `CLOUDFLARE_CUSTOM_DOMAIN` to the hostname, for example `otello.example.com`, and set `CLOUDFLARE_PUBLIC_URL` to the matching HTTPS URL. The renderer sets `custom_domain: true` and disables `workers.dev`.

The hostname must be inside a Cloudflare-managed zone and must not conflict with an existing CNAME. Cloudflare handles the DNS record/certificate for a Worker Custom Domain.

## 9. Observability and CPU check

Production config enables Workers Logs with 100% head sampling during initial go-live. After several normal 30-minute refreshes and at least one full Workflow run, inspect:

- Worker invocation outcome/errors;
- CPU time and wall time;
- exceeded CPU/memory events;
- Workflow step failures/retries;
- `job_runs` and `source_health` in D1;
- R2 object creation for source archive/snapshots.

If normal CPU usage is comfortably below the 60 s cap, lower the cap later. The Worker isolate memory ceiling remains 128 MiB, so the existing bounded/streaming source policies stay mandatory.

## 10. D1 Time Travel restore drill

D1 Time Travel restore is destructive and overwrites the selected database in place. Do not use the production database for an experimental restore while the site is live.

Before go-live, use a dedicated restore-drill D1 database or a controlled maintenance window:

```bash
npx wrangler d1 time-travel info <database>
npx wrangler d1 time-travel info <database> --timestamp="<RFC3339>"
```

Record the bookmark, make a harmless known mutation in the drill database, restore to the bookmark/timestamp, and verify that the mutation disappears. Keep the Phase 15.6 R2 logical snapshot as an independent audit artifact; it does not replace Time Travel.

## 11. Final production acceptance

Go-live is accepted only when all of the following are true:

- remote D1 contains the validated cutover history;
- remote D1 migrations are current;
- Worker deploy succeeds from GitHub;
- `/api/health` returns healthy Cloudflare/D1 state;
- dashboard summary is `ready`;
- a 30-minute scheduled refresh completes without unexpected `PARTIAL`/`FAILED`;
- one daily full Workflow completes;
- Workers Logs show no CPU/memory limit failures;
- expected raw files/PDF/snapshot appear in R2;
- Custom Domain HTTPS works if enabled;
- D1 restore drill has been completed safely.
