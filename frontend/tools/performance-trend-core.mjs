/**
 * Pure synthetic performance trend calculations. Times are rounded milliseconds.
 * Samples represent one completed test run, not an individual site visitor.
 */
export const TREND_DAYS = 7;
export const MIN_SAMPLES = 6;
export const MIN_DISTINCT_DAYS = 3;

export const THRESHOLDS = Object.freeze({
  cold: { fraction: 0.35, minIncreaseMs: 500, minCurrentMs: 1000 },
  navigation: { fraction: 0.35, minIncreaseMs: 300, minCurrentMs: 600 },
  api: { fraction: 0.45, minIncreaseMs: 150, minCurrentMs: 250 },
  firstUncached: { fraction: 0.45, minIncreaseMs: 600, minCurrentMs: 1500 },
});

export function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const center = Math.floor(sorted.length / 2);
  const middle = sorted.length % 2
    ? sorted[center]
    : (sorted[center - 1] + sorted[center]) / 2;
  return Math.round(middle);
}

// Cloudflare statuses are explicit evidence. Never infer a MISS from a slow
// response, nor count STALE/UPDATING/unknown as an origin request.
const UNCACHED_STATUSES = new Set(["MISS", "EXPIRED", "BYPASS", "DYNAMIC", "REVALIDATED"]);
export const SLOW_FIRST_UNCACHED_MS = 2000;

export function cacheClass(status) {
  if (typeof status !== "string") return "unknown";
  const normalized = status.trim().toUpperCase();
  if (normalized === "HIT") return "hit";
  if (UNCACHED_STATUSES.has(normalized)) return "uncached";
  return "unknown";
}

export function classifiedApiSamples(api) {
  const times = Array.isArray(api?.sampleTotalMs) ? api.sampleTotalMs : [];
  const statuses = Array.isArray(api?.cfCacheStatus) ? api.cfCacheStatus : [];
  const hit = [];
  const uncached = [];
  let unknownCount = 0;
  for (let i = 0; i < times.length; i++) {
    if (!validTime(times[i])) continue;
    const kind = cacheClass(statuses[i]);
    if (kind === "hit") hit.push(times[i]);
    else if (kind === "uncached") uncached.push(times[i]);
    else unknownCount++;
  }
  return {
    hitMedianMs: median(hit),
    uncachedMedianMs: median(uncached),
    firstUncachedMs: validTime(times[0]) && cacheClass(statuses[0]) === "uncached"
      ? times[0] : null,
    hitCount: hit.length,
    uncachedCount: uncached.length,
    unknownCount,
  };
}

function validTime(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

export function collectReports(reports, asOf) {
  const end = new Date(asOf).getTime();
  if (!Number.isFinite(end)) throw new Error("Invalid trend reference date");
  const earliest = end - 2 * TREND_DAYS * 24 * 60 * 60 * 1000;
  const seen = new Set();
  return reports.filter((report) => {
    const stamp = typeof report?.checkedAt === "string" ? report.checkedAt : "";
    const time = Date.parse(stamp);
    if (!Number.isFinite(time) || time < earliest || time > end || seen.has(stamp)) return false;
    if (!Array.isArray(report.browser) || !Array.isArray(report.navigation)) return false;
    seen.add(stamp);
    return true;
  }).sort((a, b) => Date.parse(a.checkedAt) - Date.parse(b.checkedAt));
}

export function seriesTrend(reports, extractor, asOf, threshold) {
  const end = new Date(asOf).getTime();
  const split = end - TREND_DAYS * 24 * 60 * 60 * 1000;
  const all = reports.map((report) => ({
    checkedAt: report.checkedAt,
    value: extractor(report),
  })).filter((point) => validTime(point.value));

  const recent = all.filter((p) => Date.parse(p.checkedAt) >= split);
  const previous = all.filter((p) => Date.parse(p.checkedAt) < split);
  const currentMedianMs = median(recent.map((p) => p.value));
  const priorMedianMs = median(previous.map((p) => p.value));
  const currentDays = new Set(recent.map((p) => p.checkedAt.slice(0, 10))).size;
  const priorDays = new Set(previous.map((p) => p.checkedAt.slice(0, 10))).size;

  const enough = recent.length >= MIN_SAMPLES &&
    previous.length >= MIN_SAMPLES &&
    currentDays >= MIN_DISTINCT_DAYS && priorDays >= MIN_DISTINCT_DAYS &&
    priorMedianMs > 0;
  const changeMs = currentMedianMs !== null && priorMedianMs !== null
    ? currentMedianMs - priorMedianMs : null;
  const changePct = changeMs !== null && priorMedianMs > 0
    ? Math.round(changeMs / priorMedianMs * 1000) / 10 : null;
  // Require that the last TWO tests are also slow, so one bad runner isn't enough.
  const lastTwo = recent.slice(-2);
  const persistent = lastTwo.length === 2 && lastTwo.every((p) =>
    p.value > priorMedianMs * 1.25 &&
    p.value - priorMedianMs >= threshold.minIncreaseMs / 2
  );

  return {
    currentMedianMs,
    priorMedianMs,
    currentSamples: recent.length,
    priorSamples: previous.length,
    currentDays,
    priorDays,
    changeMs,
    changePct,
    comparable: enough,
    regression: Boolean(
      enough && persistent &&
      currentMedianMs >= threshold.minCurrentMs &&
      changeMs >= threshold.minIncreaseMs &&
      changeMs / priorMedianMs >= threshold.fraction
    ),
  };
}

/** Sustained slow first origin/bypass response, including when the 7d baseline
 * was already slow. Require six usable runs on three distinct days, and 3/4
 * recent non-HIT first calls >=2s (including the last two, on >=2 days).
 * Unknown cache statuses and missing runs cannot silently count as evidence.
 */
export function persistentSlowFirstUncached(reports, endpoint, asOf) {
  const cutoff = Date.parse(asOf) - TREND_DAYS * 86400000;
  const recent = reports.filter((r) => Date.parse(r.checkedAt) >= cutoff)
    .map((r) => ({
      checkedAt: r.checkedAt,
      value: classifiedApiSamples(r.api?.find((a) => a.endpoint === endpoint)).firstUncachedMs,
    }));
  const valid = recent.filter((r) => validTime(r.value));
  const days = new Set(valid.map((r) => r.checkedAt.slice(0, 10))).size;
  const lastFour = recent.slice(-4);
  const slowCount = lastFour.filter((r) =>
    validTime(r.value) && r.value >= SLOW_FIRST_UNCACHED_MS).length;
  const lastTwo = lastFour.slice(-2);
  const distinctDays = new Set(lastFour.map((r) => r.checkedAt.slice(0, 10))).size;
  const persistent = valid.length >= MIN_SAMPLES && days >= MIN_DISTINCT_DAYS &&
    lastFour.length === 4 && lastFour.every((r) => validTime(r.value)) &&
    distinctDays >= 2 && slowCount >= 3 &&
    lastTwo.every((r) => r.value >= SLOW_FIRST_UNCACHED_MS);
  return { persistent, thresholdMs: SLOW_FIRST_UNCACHED_MS, slowCount,
    lastFourCount: lastFour.length, recentSamples: valid.length, recentDays: days };
}

/** Reliability is tracked separately from successful-response medians.
 * Older artifacts may lack the new fields, so use only observations they contain.
 */
export function summarizeReliability(reports, asOf) {
  const cutoff = Date.parse(asOf) - TREND_DAYS * 86400000;
  const current = collectReports(reports, asOf).filter((report) =>
    Date.parse(report.checkedAt) >= cutoff);
  const coldLoads = current.reduce((sum, r) => sum + r.browser.length, 0);
  const recoveredCold = current.reduce((sum, r) =>
    sum + (r.recoveredColdLoads?.length || 0), 0);
  const recoveredTimeouts = current.reduce((sum, r) =>
    sum + (r.api || []).reduce((n, a) => n + (a.timeoutRetries || 0), 0), 0);
  // Historical reports only stored one maximum per endpoint. Those maxima
  // cannot be counted as individual samples; exclude them from the denominator.
  const detailedRuns = current.filter((r) =>
    (r.api || []).some((a) => Array.isArray(a.sampleTotalMs)));
  const apiSampleCount = detailedRuns.reduce((sum, r) => sum +
    (r.api || []).reduce((n, a) => n + (Array.isArray(a.sampleTotalMs)
      ? a.sampleTotalMs.filter((ms) => Number.isFinite(ms) && ms >= 0).length : 0), 0), 0);
  const apiSpikes = detailedRuns.reduce((sum, r) => sum +
    (r.api || []).reduce((n, a) => n + (Array.isArray(a.sampleTotalMs)
      ? a.sampleTotalMs.filter((ms) => Number.isFinite(ms) && ms >= 1500).length : 0), 0), 0);
  const classified = detailedRuns.flatMap((r) =>
    (r.api || []).map((api) => classifiedApiSamples(api)));
  const hitApiSamples = classified.reduce((n, x) => n + x.hitCount, 0);
  const uncachedApiSamples = classified.reduce((n, x) => n + x.uncachedCount, 0);
  const unknownCacheApiSamples = classified.reduce((n, x) => n + x.unknownCount, 0);
  const slowFirstUncachedSamples = classified.reduce((n, x) =>
    n + (x.firstUncachedMs != null && x.firstUncachedMs >= SLOW_FIRST_UNCACHED_MS ? 1 : 0), 0);
  const slowColdLoads = current.reduce((sum, r) =>
    sum + r.browser.filter((b) => b.firstDataMs >= 3000).length, 0);
  return {
    completeRuns: current.length,
    coldLoads,
    firstPassColdLoads: coldLoads - recoveredCold,
    recoveredColdLoads: recoveredCold,
    recoveredApiTimeouts: recoveredTimeouts,
    detailedApiRuns: detailedRuns.length,
    legacyApiRuns: current.length - detailedRuns.length,
    apiSampleCount,
    slowApiSamples: apiSpikes,
    hitApiSamples,
    uncachedApiSamples,
    unknownCacheApiSamples,
    slowFirstUncachedSamples,
    slowColdLoads,
    // Failed or HTTP-429 runs are intentionally not part of this denominator.
    scope: "completed_unthrottled_runs",
  };
}

export function buildTrends(rawReports, asOf, routes) {
  const reports = collectReports(rawReports, asOf);
  const rowRoutes = routes.map(({ label, hash }) => ({
    route: hash,
    label,
    cold: seriesTrend(reports, (r) =>
      r.browser.find((v) => v.route === hash)?.firstDataMs, asOf, THRESHOLDS.cold),
    navigation: seriesTrend(reports, (r) =>
      r.navigation.find((v) => v.route === hash)?.navigationMs, asOf, THRESHOLDS.navigation),
  }));
  const apiNames = [...new Set(reports.flatMap((r) =>
    Array.isArray(r.api) ? r.api.map((x) => x.endpoint) : []
  ))].sort();
  const apis = apiNames.map((endpoint) => ({
    endpoint,
    // Retain the original mixed median in JSON for backwards compatibility;
    // it is NOT used to judge cache-MISS or cache-HIT performance.
    timing: seriesTrend(reports, (r) =>
      r.api?.find((v) => v.endpoint === endpoint)?.medianTotalMs, asOf, THRESHOLDS.api),
    firstUncached: seriesTrend(reports, (r) =>
      classifiedApiSamples(r.api?.find((v) => v.endpoint === endpoint)).firstUncachedMs,
      asOf, THRESHOLDS.firstUncached),
    cacheHit: seriesTrend(reports, (r) =>
      classifiedApiSamples(r.api?.find((v) => v.endpoint === endpoint)).hitMedianMs,
      asOf, THRESHOLDS.api),
    slowFirstUncached: persistentSlowFirstUncached(reports, endpoint, asOf),
  }));
  const regressions = [
    ...rowRoutes.flatMap((r) => [
      ...(r.cold.regression ? [{ scope: "Direkte åpning", key: r.label, ...r.cold }] : []),
      ...(r.navigation.regression ? [{ scope: "Sideskifte", key: r.label, ...r.navigation }] : []),
    ]),
    ...apis.flatMap((a) => [
      ...(a.firstUncached.regression
        ? [{ scope: "Første API-kall uten cachetreff", key: a.endpoint, ...a.firstUncached }] : []),
      ...(a.cacheHit.regression
        ? [{ scope: "API-cachetreff", key: a.endpoint, ...a.cacheHit }] : []),
    ]),
  ];
  return {
    generatedAt: asOf,
    currentWindowDays: TREND_DAYS,
    previousWindowDays: TREND_DAYS,
    minSamples: MIN_SAMPLES,
    minDistinctDays: MIN_DISTINCT_DAYS,
    reportCount: reports.length,
    reliability: summarizeReliability(reports, asOf),
    routes: rowRoutes,
    apis,
    slowFirstUncached: apis.filter((a) => a.slowFirstUncached.persistent).map((a) => ({
      endpoint: a.endpoint, ...a.slowFirstUncached,
      medianMs: a.firstUncached.currentMedianMs,
    })),
    regressions,
  };
}
