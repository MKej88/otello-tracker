import assert from "node:assert/strict";
import test from "node:test";
import { buildTrends, collectReports, median, seriesTrend, summarizeReliability, THRESHOLDS } from "./performance-trend-core.mjs";

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
  }
  const trend = buildTrends(samples, NOW, [{ label: "Brasil", hash: "#brasil" }]);
  assert.equal(trend.routes[0].navigation.regression, true);
  assert.equal(trend.apis[0].timing.regression, true);
  assert.deepEqual(trend.regressions.map((item) => item.scope), ["Sideskifte", "API"]);
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
  assert.equal(value.slowApiSamples, 3);
  assert.equal(value.slowColdLoads, 1);
  assert.equal(value.scope, "completed_unthrottled_runs");
});
