# BRL/NOK via Exchangerate.dev — activated after provider approval

## Permission and attribution

The owner of OtelloTracker confirmed on 2026-10-26 that permission has
been granted to use Exchangerate.dev in OtelloTracker, including the public
rate/API redistribution use case discussed before activation.
Provider default Terms otherwise prohibit passing raw and derived data through
a public API without a separate written agreement:
https://exchangerate.dev/terms

Retain the provider's written approval with the site's operating records.
This repo documents the owner's approval, but does not contain the provider's
written correspondence.

The Free/keyless plan requires a visible linked credit `Rates by Exchangerate.dev`
on **every** page containing its rates. The dashboard's persistent footer
provides the credit and describes the indicative nature of the FX feed.
If the provider has granted different terms, document them separately.

## Active ingestion

- Every 30 minutes the scheduled Worker requests:
  `https://api.exchangerate.dev/v1/latest/BRL?symbols=NOK`.
- No key is required: the documented public endpoint permits anonymous requests.
  2/hour is below the keyless allowance of 100/hour per IP, barring other
  traffic from the shared Cloudflare egress IP. A server-only rotated
  `EXCHANGERATE_DEV_API_KEY` secret can optionally be set later to use
  the account's quota; never put a key in this repository, HTML, a GitHub variable,
  request query string, public dashboard, or logs.
- `EXR_DATA_LICENSE_APPROVED=true` is embedded in production Worker configuration
  based on owner's approval. `EXR_MARKET_FX_ENABLED=true` by default in the
  production rendering. To temporarily disable polling, set GitHub
  **production environment variable** `CLOUDFLARE_EXR_MARKET_FX_ENABLED=false`
  and rerun the normal tested production deployment. Local test builds retain
  their original default OFF until explicitly configured.
- Rejects invalid, closed-market, stale, implausible or future quotes; requires
  today's Oslo-date observation no more than 75 minutes old and a rate within
  12% of a recent Norges Bank rate. A failed request is non-blocking.
- Current-day NAV source lookup prefers a fresh EXCHANGERATE_DEV observation
  when present. Historical dates and stale/missing indicative values still
  use Norges Bank. Five-year FX history and historical series remain official.
- The FX page's spot uses the source-backed BRL/NOK of the latest NAV snapshot
  when it is indicative; its historical periods are still based on Norges Bank.
- No official accounting, regulatory, or settlement use.
- Keyless polling normally needs <= 48 calls/day; no monthly account quota is
  consumed by the optional key when it is not configured.

## Verification and operation

1. Check the release's CI and production HTTP acceptance.
2. After a normal 30-minute tick, inspect the fast-refresh job step
   `exchangerate_dev_fx`: `status=ok` and `source=EXCHANGERATE_DEV`
   mean a new, validated observation was recorded.
3. Check the /api/dashboard/summary `market_timestamps.brl_nok.source`.
   It switches to `EXCHANGERATE_DEV` only after a fresh NAV recalculation.
4. After market close or an API failure, Norges Bank remains the fallback.
5. The source quote is delayed by at least 15 minutes; the NAV calculation
   and currency page are not real-time quotes.
6. Optional: rotate the API key shared in chat before ever using it.
   The current keyless integration deliberately does **not** use that key.
7. If disabling urgently during an incident, rolling back to the preceding
   Worker or removing the latest EXR observations from D1 ensures immediate
   cessation of the new NAV quote. Disabling polling alone does not instantly
   remove existing current-day observations (they naturally expire within
   75 minutes). The GitHub environment flag persists between deployments.

Provider API: https://exchangerate.dev/docs/api-reference
Provider terms: https://exchangerate.dev/terms
