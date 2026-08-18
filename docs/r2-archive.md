# Phase 15.6 – R2 source archive

Phase 15.6 adds a content-addressed R2 audit trail around the existing D1/Worker model. It does **not** change CORE/FULL NAV, option valuation, buyback forecasting, or market-source priority.

## Runtime flow

The daily `FullRefreshWorkflow` keeps the Phase 15.5 sequence and adds archive/enrichment steps:

```text
ECB refresh ---------> raw ECB CSV in R2
B3 refresh ----------> raw daily COTAHIST ZIP in R2
CVM refresh ---------> D1 metadata (unchanged financial semantics)
NewsWeb reconcile ---> weekly buyback / company-news facts
                     -> NewsWeb transaction PDF fetch
                     -> exact PDF bytes in R2
                     -> pypdf text extraction
                     -> deterministic OTEC transaction parser
                     -> reconciliation to canonical weekly buyback
                     -> buyback_daily_transactions
                     -> replace weekly fallback cash with exact daily cash timing
OTEC EOD ------------> existing Phase 15.5 R2 recovery when needed
NAV dirty refresh ---> same financial models
D1 preflight --------> same readiness checks
D1 snapshot ---------> gzip logical snapshot + manifest in R2
```

A failure in attachment parsing never invents daily facts. The weekly buyback remains the conservative fallback until the PDF can be reconciled.

## R2 key policy

Raw objects are content-addressed:

```text
raw/<source>/<kind>/<logical-date>/<sha20>-<sanitized-filename>
```

Examples:

```text
raw/ecb/exr/2026-08-17/<sha>-exr-2026-07-27-2026-08-17.csv
raw/b3/cotahist-daily/2026-08-17/<sha>-COTAHIST_D17082026.ZIP
raw/newsweb/buyback-pdf/2026-08-17/<sha>-Transaksjonsoversikt.pdf
raw/euronext/otec/2026-08-17/current-trading-day-<sha>.zip
```

Reprocessing the same bytes therefore targets the same key. D1 `source_documents` stores the SHA-256 and R2 key used for the parsed facts.

## NewsWeb PDF rules

Only the transaction attachment associated with a `share buyback program status` message is used for automatic daily cash timing. A candidate must:

1. be a PDF;
2. have a transaction-oriented filename;
3. parse into OTEC buy trades only;
4. have no OTEC sell rows;
5. reconcile daily shares exactly to the canonical weekly total;
6. reconcile NOK amount inside the configured absolute/relative tolerance;
7. reconcile weighted average price to the weekly status.

If any condition fails, no daily row or cash replacement is applied automatically.

Validated rows are stored in `buyback_daily_transactions`. The weekly `buybacks` row remains the reconciliation/audit summary. Once valid daily rows exist, the corresponding `OTELLO_BUYBACK` weekly cash movement is removed and replaced by `OTELLO_BUYBACK_DAILY` movements on the actual trade dates.

## Python dependency

`pypdf==6.16.1` is bundled by `pywrangler` from `cloudflare/pyproject.toml`. It is pure Python and is used only by the heavier Workflow attachment step, not the 30-minute fast path.

## D1 logical snapshot

Every successful Workflow attempt also tries to write:

```text
snapshots/d1/<target-date>/logical-<sha20>.json.gz
snapshots/d1/<target-date>/manifest-<sha20>.json
```

The snapshot is deterministic, row-ordered and gzip-compressed with a fixed gzip timestamp. The manifest records row counts, logical SHA-256, compressed SHA-256, sizes and preflight status.

This is an **audit/logical recovery artifact**, not a replacement for D1 Time Travel. Remote Time Travel/restore is still explicitly tested in Phase 15.7.

## Historical import files

`historical_import_archive.archive_historical_import()` defines the cutover/backfill contract for user/provider files such as Investing.com OTEC CSV, official Euronext historical exports, B3 archives and manual validated inputs. Exact bytes are stored first/alongside import together with a content-addressed manifest.

The code path is CI-testable without a remote bucket. The historical files themselves can only be populated into the production R2 bucket after the actual Cloudflare resources are created during go-live.

## Remote resources

No production R2 bucket is created by this phase. The repository continues to use local/CI bindings until Phase 15.7 creates and connects the actual account resources.
