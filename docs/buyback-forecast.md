# Otello weekly buyback forecast

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
