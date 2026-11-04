import assert from "node:assert/strict";
import test from "node:test";
import { buildTrends, cacheClass, classifiedApiSamples, collectReports, median, persistentSlowFirstUncached, seriesTrend, summarizeReliability, THRESHOLDS } from "./performance-trend-core.mjs";

const NOW = "2026-10-19T20:00:00.000Z";
const DAY_MS = 86400000;
const atDay = (offset, hour = 10) =>
  new Date(Date.parse("2026-10-19T00:00:00.000Z") - offset * DAY_MS + hour * 3600000).toISOString();

function report(offset, firstDataMs, navigationMs = 420, checkedAt = atDay(offset)) {
  return {
    checkedAt,
    browser: [{ route: "#brasil", firstDataMs }],
    navigation: [{ route: "#brasil", navigationMs }],
    api: [{ endpoint: "/api/brazil/dashboard", medianTotalMs: 120 }],
    errors: [],
  };
}

function bothWeeks(oldValue, newValue) {
  const previous = [13, 12, 11, 10, 9, 8].map((i) => report(i, oldValue));
  const recent = [6, 5, 4, 3, 2, 1].map((i) => report(i, newValue));
  return [...previous, ...recent];
}

test("median rounds the two middle values correctly", () => {
  assert.equal(median([2, 10, 7, 5]), 6);
  assert.equal(median([1, 5, 2]), 2);
  assert.equal(median([]), null);
});

test("rolling 7 days median and prior 7 days trigger persistent regression", () => {
  const trend = buildTrends(bothWeeks(700, 1350), NOW, [{ label: "Brasil", hash: "#brasil" }]);
  assert.equal(trend.reportCount, 12);
  assert.equal(trend.routes[0].cold.priorMedianMs, 700);
  assert.equal(trend.routes[0].cold.currentMedianMs, 1350);
  assert.equal(trend.routes[0].cold.changePct, 92.9);
  assert.equal(trend.routes[0].cold.currentSamples, 6);
  assert.equal(trend.routes[0].cold.priorSamples, 6);
  assert.equal(trend.routes[0].cold.comparable, true);
  assert.equal(trend.routes[0].cold.regression, true);
  assert.deepEqual(trend.regressions.map((item) => item.scope), ["Direkte åpning"]);
  assert.equal(trend.routes[0].navigation.regression, false);
  assert.equal(trend.apis[0].timing.regression, false);
});

test("one slow GitHub runner cannot trigger an alarm if weekly trend is stable", () => {
  const samples = bothWeeks(700, 700);
  samples.at(-1).browser[0].firstDataMs = 4000;
  const trend = buildTrends(samples, NOW, [{ label: "Brasil", hash: "#brasil" }]);
  assert.equal(trend.routes[0].cold.currentMedianMs, 700);
  assert.equal(trend.routes[0].cold.regression, false);
});

test("requires both enough samples AND three separate days per week", () => {
  const sameDay = [
    ...Array.from({ length: 6 }, (_, i) => report(10, 600, 400, atDay(10, i + 3))),
    ...Array.from({ length: 6 }, (_, i) => report(3, 1800, 950, atDay(3, i + 3))),
  ];
  const trend = buildTrends(sameDay, NOW, [{ label: "Brasil", hash: "#brasil" }]);
  assert.equal(trend.routes[0].cold.comparable, false);
  assert.equal(trend.routes[0].cold.regression, false);
});

test("requires the last two measurements to show continuing slowness", () => {
  const samples = bothWeeks(600, 1700);
  samples.at(-1).browser[0].firstDataMs = 610;
  samples.at(-2).browser[0].firstDataMs = 620;
  const trend = buildTrends(samples, NOW, [{ label: "Brasil", hash: "#brasil" }]);
  assert.equal(trend.routes[0].cold.currentMedianMs, 1700);
  assert.equal(trend.routes[0].cold.regression, false);
});

test("small absolute changes do not trigger regression despite high percent", () => {
  const samples = bothWeeks(100, 170);
  const trend = buildTrends(samples, NOW, [{ label: "Brasil", hash: "#brasil" }]);
  assert.equal(trend.routes[0].cold.changePct, 70);
  assert.equal(trend.routes[0].cold.regression, false);
});

test("navigation has separate threshold and route, API has own threshold", () => {
  const samples = bothWeeks(800, 800);
  for (const report of samples) {
    const recent = Date.parse(report.checkedAt) >= Date.parse(NOW) - 7 * DAY_MS;
    report.navigation[0].navigationMs = recent ? 950 : 400;
    report.api[0].medianTotalMs = recent ? 500 : 120;
    report.api[0].sampleTotalMs = [recent ? 500 : 120, recent ? 510 : 130, recent ? 490 : 110];
    report.api[0].cfCacheStatus = ["HIT", "HIT", "HIT"];
  }
  const trend = buildTrends(samples, NOW, [{ label: "Brasil", hash: "#brasil" }]);
  assert.equal(trend.routes[0].navigation.regression, true);
  assert.equal(trend.apis[0].timing.regression, true);
  assert.deepEqual(trend.regressions.map((item) => item.scope), ["Sideskifte", "API-cachetreff"]);
});

test("out-of-window, future and duplicated runs are excluded", () => {
  const data = [
    report(15, 800),
    report(2, 600),
    report(2, 800),
    report(-1, 900),
    report(11, 500),
    { checkedAt: "bad", browser: [], navigation: [] },
  ];
  assert.deepEqual(collectReports(data, NOW).map((r) => r.browser[0].firstDataMs), [500, 600]);
});

test("invalid and missing per-page data are skipped independently", () => {
  const data = bothWeeks(700, 1700);
  data[0].browser[0].firstDataMs = Number.NaN;
  const trend = buildTrends(data, NOW, [{ label: "Brasil", hash: "#brasil" }, { label: "NAV", hash: "#nav" }]);
  assert.equal(trend.routes[0].cold.priorSamples, 5);
  assert.equal(trend.routes[0].cold.regression, false);
  assert.equal(trend.routes[1].cold.currentMedianMs, null);
  assert.equal(trend.routes[1].cold.regression, false);
});

test("recovered attempts and API tail latency are counted separately from weekly medians", () => {
  const recovered = report(1, 3200);
  recovered.recoveredColdLoads = [{ route: "#brasil", attempts: [{ outcome: "failed" }, { outcome: "success" }] }];
  recovered.api[0].sampleTotalMs = [20, 1700, 2100];
  recovered.api[0].timeoutRetries = 1;
  const olderArtifact = report(2, 600);
  olderArtifact.api[0].maxTotalMs = 2000;
  const outsideWeek = report(10, 4000);
  const value = summarizeReliability([recovered, olderArtifact, outsideWeek], NOW);
  assert.equal(value.completeRuns, 2);
  assert.equal(value.coldLoads, 2);
  assert.equal(value.firstPassColdLoads, 1);
  assert.equal(value.recoveredColdLoads, 1);
  assert.equal(value.recoveredApiTimeouts, 1);
  assert.equal(value.slowApiSamples, 2);
  assert.equal(value.hitApiSamples, 0);
  assert.equal(value.uncachedApiSamples, 0);
  assert.equal(value.unknownCacheApiSamples, 3);
  assert.equal(value.apiSampleCount, 3);
  assert.equal(value.detailedApiRuns, 1);
  assert.equal(value.legacyApiRuns, 1);
  assert.equal(value.slowColdLoads, 1);
  assert.equal(value.scope, "completed_unthrottled_runs");
});

test("cache classes are evidence based; unknown and stale never become misses", () => {
  assert.equal(cacheClass("miss"), "uncached");
  assert.equal(cacheClass("EXPIRED"), "uncached");
  assert.equal(cacheClass("BYPASS"), "uncached");
  assert.equal(cacheClass("REVALIDATED"), "uncached");
  assert.equal(cacheClass("HIT"), "hit");
  for (const status of ["STALE", "UPDATING", "ikke oppgitt", undefined, ""]) {
    assert.equal(cacheClass(status), "unknown");
  }
  const classified = classifiedApiSamples({
    sampleTotalMs: [2300, 25, 30, 2500, 45],
    cfCacheStatus: ["MISS", "HIT", "HIT", "STALE", "BYPASS"],
  });
  assert.equal(classified.firstUncachedMs, 2300);
  assert.equal(classified.uncachedMedianMs, 1173);
  assert.equal(classified.hitMedianMs, 28);
  assert.equal(classified.hitCount, 2);
  assert.equal(classified.uncachedCount, 2);
  assert.equal(classified.unknownCount, 1);
  assert.equal(classifiedApiSamples({
    sampleTotalMs: [35, 2400, 50], cfCacheStatus: ["HIT", "MISS", "HIT"],
  }).firstUncachedMs, null);
  assert.equal(classifiedApiSamples({
    sampleTotalMs: [2300, 20, 25], cfCacheStatus: [null, "HIT", "HIT"],
  }).firstUncachedMs, null);
  assert.equal(classifiedApiSamples({ medianTotalMs: 3000 }).firstUncachedMs, null);
});

function withCacheEvidence(samples, first, hit = 30, status = "MISS") {
  for (const item of samples) {
    const recent = Date.parse(item.checkedAt) >= Date.parse(NOW) - 7 * DAY_MS;
    item.api[0].sampleTotalMs = [recent ? first[1] : first[0], hit, hit];
    item.api[0].cfCacheStatus = [status, "HIT", "HIT"];
    item.api[0].medianTotalMs = hit; // Original mixed median hides slow first request.
  }
  return samples;
}

test("first non-HIT is trended and alerted independently of healthy cache HITs", () => {
  const samples = withCacheEvidence(bothWeeks(750, 750), [700, 2500]);
  const trend = buildTrends(samples, NOW, [{ label: "Brasil", hash: "#brasil" }]);
  const row = trend.apis[0];
  assert.equal(row.timing.currentMedianMs, 30);
  assert.equal(row.firstUncached.priorMedianMs, 700);
  assert.equal(row.firstUncached.currentMedianMs, 2500);
  assert.equal(row.firstUncached.regression, true);
  assert.equal(row.cacheHit.currentMedianMs, 30);
  assert.equal(row.cacheHit.regression, false);
  assert.equal(row.slowFirstUncached.persistent, true);
  assert.deepEqual(trend.regressions.map((r) => r.scope), ["Første API-kall uten cachetreff"]);
  assert.equal(trend.slowFirstUncached.length, 1);
});

test("persistent slow first non-HIT is reported even without a week-on-week regression", () => {
  const samples = withCacheEvidence(bothWeeks(750, 750), [2400, 2400], 25, "EXPIRED");
  const trend = buildTrends(samples, NOW, [{ label: "Brasil", hash: "#brasil" }]);
  assert.equal(trend.apis[0].firstUncached.regression, false);
  assert.equal(trend.apis[0].slowFirstUncached.persistent, true);
  assert.equal(trend.slowFirstUncached[0].medianMs, 2400);
  assert.equal(trend.regressions.length, 0);
});

test("one spike, unknown status, few runs, or a single day cannot trigger persistent alerts", () => {
  const samples = withCacheEvidence(bothWeeks(750, 750), [2100, 900], 25);
  samples.at(-1).api[0].sampleTotalMs[0] = 3500;
  assert.equal(buildTrends(samples, NOW, []).slowFirstUncached.length, 0);
  samples.at(-1).api[0].cfCacheStatus[0] = "unknown";
  assert.equal(classifiedApiSamples(samples.at(-1).api[0]).firstUncachedMs, null);
  const few = withCacheEvidence([report(1, 750), report(2, 750)], [2000, 4000]);
  assert.equal(persistentSlowFirstUncached(few, "/api/brazil/dashboard", NOW).persistent, false);
  const sameDay = withCacheEvidence(Array.from({ length: 6 }, (_, i) =>
    report(2, 750, 420, atDay(2, i + 3))), [2300, 2300]);
  assert.equal(persistentSlowFirstUncached(sameDay, "/api/brazil/dashboard", NOW).persistent, false);
});

test("old reports without cache status do not invent HIT or MISS observations", () => {
  const samples = bothWeeks(750, 750);
  const row = buildTrends(samples, NOW, []).apis[0];
  assert.equal(row.timing.currentMedianMs, 120);
  assert.equal(row.firstUncached.currentMedianMs, null);
  assert.equal(row.cacheHit.currentMedianMs, null);
  assert.equal(row.firstUncached.comparable, false);
  assert.equal(row.cacheHit.comparable, false);
  assert.equal(row.slowFirstUncached.persistent, false);
});
