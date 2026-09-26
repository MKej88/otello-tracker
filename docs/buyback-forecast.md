# Otello weekly buyback forecast

Production model proposed in this change: `otec-buyback-robust-volume-v2`.

## Why the model changes

The live response on 26 September 2026 reproduced the reported problem: 16 weeks,
24.43% WMAPE, and predictions of 102,727 / 93,592 / 89,118 against actual purchases
of 54,388 / 36,129 / 40,297 in the three latest weeks. It still labelled the next
forecast HIGH confidence because it looked only at the full-period median error.

Two effects amplify the overshoot: an extreme daily-volume observation remains
in ADV20 for four weeks, while the median of eight utilisation observations reacts
slowly to falling purchases. The historical test also counted the target week's
observed volume rows as trading days. Missing data thereby became a retrospectively
shortened trading week (four days on 24–28 August), which was not knowable ex ante.

## Current methodology

1. Freeze the last 20 positive-volume observations before the forecast week, retaining
   the existing source series and raw ADV20 / week-start capacity fields.
2. For **forecasting only**, cap each daily volume at three times the median of the
   same window. The API separately exposes `forecast_adv20_shares`,
   `forecast_capacity_estimate_shares`, `volume_outlier_days` and
   `volume_adjustment_pct`. A sustained volume rise can raise the median normally.
3. Learn utilisation on that same adjusted capacity basis, using the latest four
   available programme weeks with chronological weights 1, 2, 3, 4. With fewer than
   two observations, use 1.0; constrain the resulting factor to 0–1.10. This avoids
   calibrating on raw spike-inflated capacity and applying the factor to a different basis.
4. Use the exchange calendar for expected days in both current and historical estimates.
   A target week's missing or revised volume cannot change its prediction. Where a
   report's publication date is recorded, exclude it from earlier weeks' learning and
   remaining-share calculation.
5. Retain the remaining-programme cap and current price-cap guard. The scenario width
   uses the 80th percentile of the last eight absolute errors divided by model capacity,
   with a 12% floor (20% without history). This is an empirical range, not a calibrated
   probability interval.
6. Confidence uses the last four weeks' **weighted** error and the latest miss. Recent
   WMAPE above 25% produces LOW confidence. HIGH additionally requires at least six
   observations, WMAPE at most 10%, latest error at most 20%, an open price constraint
   and at most 20% volume damping.

Raw volumes are not overwritten. Damping is not a claim that a trade was a block
trade or that it is excluded from the regulatory volume basis. The raw weekly
capacity remains a proxy. The legal limit is tested for each purchase day using
the relevant trading-venue volume; see [Finanstilsynet](https://www.finanstilsynet.no/en/supervision/market-conduct/buy-back/)
and [Article 3 of Regulation 2016/1052](https://eur-lex.europa.eu/eli/reg_del/2016/1052/oj/eng).

## Reproducible validation (26 September 2026)

Run from `backend`:

```sh
PYTHONPATH=. python -m app.jobs.backtest_buyback_robust
```

The fixed fixture combines the existing Euronext seed with the user's Euronext
export through 18 September and 16 actual programme weeks through 25 September.
The final forecast needs only volume before 21 September, so no missing final-week
volume is fabricated. Source provenance, the export SHA-256 and the captured live
v1 rows are in `backend/tests/fixtures/buyback_forecast_september_2026.json`.

Both candidate calculations use identical source observations and the exchange
calendar. The export and the live delayed-trade aggregates differ slightly. Hence
**23.59% below must not be presented as a like-for-like replacement for the live
screenshot's 24.43%**. The latter is retained in the fixture rather than rewritten.

| Metric, 8 June–25 September (16 weeks) | Previous formula | v2 |
| --- | ---: | ---: |
| WMAPE | 23.59% | 10.32% |
| Median absolute percentage error | 7.62% | 8.03% |
| Within ±10% | 56.2% | 62.5% |
| Within ±20% | 75.0% | 87.5% |

| Week starting | Actual | Previous formula | v2 |
| --- | ---: | ---: | ---: |
| 31 August | 61,500 | 65,732 | 62,981 |
| 7 September | 54,388 | 99,158 | 59,212 |
| 14 September | 36,129 | 93,368 | 49,267 |
| 21 September | 40,297 | 84,819 | 38,478 |

The same fixed settings were also replayed across 58 older seeded programme weeks:
WMAPE improves from 22.13% to 16.23%. It is not a universal improvement: median error
rises from 13.42% to 14.85%, and weeks within ±20% fall from 71.4% to 64.3%. In the
current programme's 12 weeks before 31 August, WMAPE rises from 8.97% to 10.13%.
This is the tradeoff for avoiding very large overshoots and adapting faster.

These are retrospective comparisons, **not an untouched holdout**. Parameters were
chosen after inspecting the September failure. The validation does not reconstruct
historical price-cap changes or source publication vintages. For rows without
publication dates it assumes completed earlier reports were available. Current
source corrections can change a replay. The UI therefore labels these results as
recalculated model tests and shows the previous formula alongside; it does not
present them as archived forecasts. No original forecast archive is created by this
change. Future performance still needs observation after deployment.

## Implementation and regression coverage

- Reference backend and Worker use identical small pure model modules, checked for drift.
- Both use the same inputs and produce identical API payloads in the parity test.
- Regression cases cover the September spike, later actuals/volumes, absent target-week
  volumes, delayed report publication, raw-volume preservation, mandate exhaustion,
  price-cap blocking, uncertainty after large recent misses, and constant D1 query count.
- The API remains read-only; no schema, raw volume or ingestion changes.

---

# Historical v1 reference (superseded on 26 September 2026)

## Purpose

The dashboard estimates how many OTEC shares may be repurchased in the week after the latest weekly buyback status announcement. The forecast is explicitly an estimate, not a statement of what Pareto or another execution broker will buy.

## Regulatory basis

The model follows Article 3 of Commission Delegated Regulation (EU) 2016/1052 (Safe Harbour): purchases may not exceed 25% of average daily volume. Where the buyback programme does not state a fixed reference volume, average daily volume is based on the 20 trading days preceding the purchase date.

Primary sources:

- EUR-Lex, Delegated Regulation (EU) 2016/1052: https://eur-lex.europa.eu/eli/reg_del/2016/1052/oj/eng
- Finanstilsynet, own-share buybacks / Safe Harbour: https://www.finanstilsynet.no/
- Otello company news / NewsWeb programme and weekly status announcements: https://newsweb.oslobors.no/

Otello's current 8 June 2026 programme states a maximum programme consideration of NOK 20 per share and a maximum of 2,192,046 shares. The weekly status messages repeat those programme terms. Programme terms are parsed from the latest original NewsWeb status message and stored with provenance; the forecast does not hard-code the current NOK 20 limit.

## Forecast methodology

For an ex-ante weekly estimate, the model freezes the information available at the start of the forecast week:

1. Take OTEC's last 20 positive-volume trading days before Monday.
2. Calculate ADV20 from official Euronext `Number of Shares` / validated prior-day trade activity.
3. Calculate a week-start Safe Harbour capacity proxy:

   `0.25 × ADV20 × expected trading days`

4. Cap the result by remaining shares in the active Otello programme.
5. Estimate execution utilisation from the median utilisation of up to the latest eight completed weeks in the same active programme.
6. Produce a base estimate and an empirical range using recent walk-forward forecast errors.
7. Compare the latest OTEC close with the programme's maximum price and lower confidence / block the point estimate if the latest close is above the mandate price.

### Important distinction: proxy versus legal daily limit

The weekly capacity number is intentionally labelled `week_start_capacity_estimate_shares`. It is **not** the exact legal weekly ceiling. The regulation applies the 25% limit on each purchase day and the preceding-20-day window therefore rolls through the week. Freezing ADV20 on Monday prevents look-ahead bias in a forecast and makes historical backtests reproducible.

## Data sources

- Historical OTEC daily volume baseline: compact derived copy of the user's official Euronext historical OTEC export, source field `Number of Shares`.
- Ongoing activity: official Euronext `PREVIOUS_TRADING_DAY` delayed-trade file, aggregated only after the day is final and stored as `DELAYED_TRADE_SUM`.
- Actual repurchases: original Oslo Børs NewsWeb weekly status messages and validated transaction attachments, with the existing curated official-gap fallback.
- Programme price/max-share terms: latest original NewsWeb weekly status.

A previous-day delayed-trade aggregate must reconcile to the known Euronext historical daily volume in the live diagnostic before this ingestion route is considered validated.

## Walk-forward backtest

The test replays each historical week using only information available before that week. No future weekly volume or future utilisation is used in that week's prediction.

Broad sample through 14 August 2026:

- 63 programme weeks from April 2025 through 14 August 2026, including two documented zero-purchase weeks.
- All-period regime-sensitive model: median absolute percentage error 10.26%, WMAPE 23.88%.
- Since 1 January 2026: median absolute percentage error 7.38%, WMAPE 10.24%; 93.5% of non-zero weeks within ±20%.
- February 2026 programme: median absolute percentage error 6.53%, WMAPE 7.73%; 100% of weeks within ±20%.
- Current 8 June 2026 programme: 10 completed weeks; median absolute percentage error 5.99%, WMAPE 9.19%; 70% within ±10% and 90% within ±20%.

The larger 2025 errors are why the production model learns primarily from the active programme rather than fitting one utilisation factor across all historical regimes.

## Forecast as of 17 August 2026

Using information through Friday 14 August 2026:

- ADV20: 52,789.4 shares/day.
- Week-start capacity estimate for 17–21 August: 65,987 shares.
- Median active-program utilisation factor: approximately 94.3%.
- Base estimate: approximately 62,200 shares.
- Empirical estimate range: approximately 58,700–65,700 shares.
- Latest Euronext close used in the frozen forecast: NOK 17.20.
- Programme maximum price: NOK 20.
- Price state: open.
- Model confidence: high.

These numbers will move automatically after new weekly buyback announcements and finalized Euronext volume observations.

## API

`GET /api/buybacks/forecast`

Returns:

- active programme and remaining programme shares;
- forecast week;
- ADV20 and week-start capacity estimate;
- latest price versus programme price cap;
- base / low / high share estimate;
- confidence and any price-cap warning;
- walk-forward metrics and recent active-program weeks.

`GET /api/system/market-activity`

Returns coverage of the OTEC volume dataset used by the forecast.
