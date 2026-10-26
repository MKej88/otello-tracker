# Indicative BRL/NOK via exchangerate.dev (staged, default OFF)

## Important release gate: redistribution rights

As of 2026-10-26, exchangerate.dev's current Terms of Service explicitly forbid
redistribution of **raw or derived exchange-rate data through your own API** on
**every plan** without a separate written agreement:
https://exchangerate.dev/terms

OtelloTracker's public `/api/dashboard/summary`, `/api/market/quotes`
and other dashboard/API responses expose the BRL/NOK rate and/or derived values.
**Do not enable this integration under the default Free terms.** Before enabling,
obtain a written grant covering the actual public endpoints and any source
attribution requirements; otherwise leave the feature disabled. Display on
Free also requires a visible credit link `Rates by Exchangerate.dev` near
the displayed rates on every relevant page. The overview credit is already
prepared but the remaining pages still need a full attribution audit.

## Implemented, safe behind feature gates

- Every 30-minute fast-refresh is able to fetch only
  `GET https://api.exchangerate.dev/v1/latest/BRL?symbols=NOK`.
- Authentication is server-side `Authorization: Bearer`, using an **independently
  rotated** Cloudflare secret `EXCHANGERATE_DEV_API_KEY`. No URL query key, logs
  or browser bundle credentials.
- Must explicitly set BOTH `EXR_MARKET_FX_ENABLED=true` and
  `EXR_DATA_LICENSE_APPROVED=true`. Both default OFF. The approval flag is a
  required manual assertion of written provider permission, not an attempt to
  claim the standard Free license allows API redistribution.
- Rejects non-live, closed-market, stale, invalid, implausible or future rates;
  requires a current-Oslo-day observation at most 75 minutes old, and checks
  +/- 12% against Norges Bank's recent published rate. No repeated writes for
  the same observation. Failures and limits are non-blocking and don't interrupt
  the existing Norges Bank feed or NAV calculation.
- Current-day NAV source lookup prefers a fresh EXCHANGERATE_DEV observation
  when present; historical dates and stale/missing intraday data still use the
  existing official Norges Bank / ECB preference. The five-year FX dashboard
  and historical series remain sourced from Norges Bank.
- The overview explanation automatically switches source text and shows the
  provider's linked credit only when NAV uses EXCHANGERATE_DEV.
- Typical quota: 48 half-hour calls x 31 days = max 1,488 calls in a
  31-day month (usually fewer due to weekend skips) against Free's 5,000.
  API quotes on the Free plan are delayed at least 15 minutes and are
  indicative, not official accounting or trade settlement rates.

## How to prepare after permission

1. Obtain and retain written permission for the public API usage described above.
2. Rotate the key shared in the chat. Store the new key as a Cloudflare Worker
   secret named `EXCHANGERATE_DEV_API_KEY` (never in GitHub, repo variables,
   frontend code, or chat).
3. Audit all public endpoints and all website screens containing provider data
   for rights and attribution, including downloads. Do not flip flags until
   compliant.
4. Configure the two opt-in variables to `true` only once approval is recorded.
5. Run the 30-minute cron and inspect job metadata `exchangerate_dev_fx`;
   verify current-day `bmob3.brl_nok_source`, fallback behavior, and NAV parity.
6. To deactivate external polling set `EXR_MARKET_FX_ENABLED=false`. Any
   previously ingested observations remain in D1 for provenance and may be
   selected while fresh (up to 75 min). For an immediate hard cutoff, remove
   current-day indicative observations and recalculate current NAV or deploy
   a reader-side disable gate before turning this on.

Provider documentation: https://exchangerate.dev/docs/api-reference
Reference terms: https://exchangerate.dev/terms
