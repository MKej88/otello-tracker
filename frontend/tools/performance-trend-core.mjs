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
    timing: seriesTrend(reports, (r) =>
      r.api?.find((v) => v.endpoint === endpoint)?.medianTotalMs, asOf, THRESHOLDS.api),
  }));
  const regressions = [
    ...rowRoutes.flatMap((r) => [
      ...(r.cold.regression ? [{ scope: "Direkte åpning", key: r.label, ...r.cold }] : []),
      ...(r.navigation.regression ? [{ scope: "Sideskifte", key: r.label, ...r.navigation }] : []),
    ]),
    ...apis.filter((a) => a.timing.regression).map((a) =>
      ({ scope: "API", key: a.endpoint, ...a.timing })),
  ];
  return {
    generatedAt: asOf,
    currentWindowDays: TREND_DAYS,
    previousWindowDays: TREND_DAYS,
    minSamples: MIN_SAMPLES,
    minDistinctDays: MIN_DISTINCT_DAYS,
    reportCount: reports.length,
    routes: rowRoutes,
    apis,
    regressions,
  };
}
