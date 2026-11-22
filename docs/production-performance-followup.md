# Production performance follow-up (2026-11-22)

## Observations and priorities
- All 12 page-load medians remain relatively stable. Most variable latency is from Cloudflare cache misses.
- `/api/fx/dashboard`: last 7-day first non-HIT median approximately 2,176 ms; several individual requests exceeded 3 s. Edge HIT responses are much faster.
- `/api/buybacks/dashboard`: first non-HIT median increased from 710 to 1,177 ms. Endpoint uses a precomputed snapshot; do not assume the financial model was recalculated on every request.
- `/api/dashboard/discount-history?days=365&max_points=72`: cache hit in the precomputed NAV period can still entail D1 lookup time. The same path also has a separate Cloudflare cache.
- Overview: occasional >250 ms main-thread tasks. Network time for JavaScript files is not a CPU measurement.
- Cloudflare migration `0005_performance_indexes.sql` already has a matching *expression index* on `substr(observed_at, 1, 10)`. Do **not** rewrite the FX SQL date filter without an EXPLAIN QUERY PLAN against real production-like D1 data.

## Changes prepared
1. Independent historical BRL/USD and approved intraday FX quote reads now overlap via asyncio.gather. Financial values and selection precedence are unchanged.
2. Allow-listed FX stage and D1 timings are exposed in Server-Timing when the Worker runs. Stages: latest-date lookup, BRL history, USD history, indicative quote, computation, handler, D1 query count and total D1 read duration. The overlapping phases **must not be summed**.
3. D1 aggregates in the existing Worker diagnostic header now cover FX, precomputed NAV discount history and buyback snapshot alongside the previous two endpoints.
4. Synthetic JSON and job summaries include the FX breakdown and maximum individual long-task duration for Overview.
5. An **opt-in**, separate EU runner job is defined but does not run unless explicitly provisioned.

## Verify post-deployment
- Inspect first non-HIT (MISS / EXPIRED / REVALIDATED / DYNAMIC / BYPASS) alongside CF-Ray and Cloudflare datacenter. Compare `fx_handler`, `fx_d1`, and the stage timings.
- If D1 reads dominate, investigate query plans, size of historical series, and materialization. If the Worker/handler is fast but send-to-header is slow, investigate Worker start, Cloudflare route, and network before changing SQL.
- Compare `otello_req_d1` and `otello_req_reads` for buybacks and NAV history; verify snapshot HIT versus live fallback separately.
- For Overview, correlate `longTaskMaxMs`, `longTaskTotalMs`, and any independent CPU sample with the same test run. Production assets are minified, so a private source map may be necessary to identify functions confidently.
- Reassess after a full additional week; do not claim real-user P95 from synthetic samples.

## Enable European synthetic runner
Register a **trusted self-hosted** Linux x64 GitHub Actions runner physically hosted in Europe, assign custom label `otello-eu`, and install Chrome/Chromium. Enforce suitable security controls and restricted egress. Then set the GitHub repository variable `OTELLO_EU_RUNNER_ENABLED=true`. Until both are present the optional job is skipped. The EU job produces its own `otello-production-performance-eu` artifact and does not enter the original US-based trend comparison.

## Real-user monitoring and privacy
**No real-user beacon or collection is enabled in this change.** Before enabling real-user telemetry, select an appropriate service and retention policy (e.g. Cloudflare Web Analytics), assess privacy/GDPR and the information shown to users, and deploy its account-specific configuration through the site owner. Avoid collecting client identifiers, user-facing query parameters or finance payloads. Keep real-user measurements separate from synthetic measurements.
