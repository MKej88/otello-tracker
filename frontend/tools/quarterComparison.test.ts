import assert from "node:assert/strict";
import test from "node:test";
import { compareQuarterMetric, type ReportedQuarter } from "../src/quarterComparison.ts";
import type { NextQuarterEstimate } from "../src/nextQuarterConsensus.ts";

const amount = (metric: string, value: number): NextQuarterEstimate => ({ metric, label: metric, value_mbrl: value });
const pct = (metric: string, value: number): NextQuarterEstimate => ({ metric, label: metric, value_pct: value });
const quarter = (...metrics: NextQuarterEstimate[]): ReportedQuarter => ({ period: "2Q26", metrics });

test("beløp viser rapporttallet og prosentendring mot begge periodene", () => {
  const estimate = amount("revenue_mbrl", 239.8);
  for (const actual of [227.3, 187.5]) {
    const comparison = compareQuarterMetric(estimate, quarter(amount("revenue_mbrl", actual)));
    assert.equal(comparison.actual, actual);
    assert.ok(Math.abs(comparison.change! - (239.8 / actual - 1) * 100) < 1e-10);
    assert.equal(comparison.isPercent, false);
  }
});

test("margin og capexandel sammenlignes i prosentpoeng fra viste verdier", () => {
  for (const [metric, estimate, actual, expected] of [
    ["ebitda_margin_pct", 35.7, 34.9, 0.8],
    ["ebitda_margin_pct", 35.7, 33.4, 2.3],
    ["capex_to_sales_pct", 6.5, 8.1, -1.6],
  ] as const) {
    const comparison = compareQuarterMetric(pct(metric, estimate), quarter(pct(metric, actual)));
    assert.equal(comparison.actual, actual);
    assert.ok(Math.abs(comparison.change! - expected) < 1e-10);
    assert.equal(comparison.isPercent, true);
  }
});

test("manglende, ugyldige og tvetydige tall holdes utenfor", () => {
  const estimate = amount("revenue_mbrl", 239.8);
  const invalidQuarters = [undefined, quarter(), quarter(pct("revenue_mbrl", 20)),
    quarter(amount("revenue_mbrl", NaN)), quarter(amount("revenue_mbrl", Infinity)),
    quarter({ ...amount("revenue_mbrl", 200), value_pct: 30 })];
  for (const report of invalidQuarters) assert.equal(compareQuarterMetric(estimate, report).actual, null);
  assert.equal(compareQuarterMetric({ ...estimate, value_pct: 20 }, quarter(estimate)).actual, null);
  assert.equal(compareQuarterMetric(amount("adjusted_net_income_mbrl", 48), quarter(amount("net_income_mbrl", 40))).actual, null);
  assert.equal(compareQuarterMetric(estimate, quarter(amount("revenue_mbrl", 0))).change, null);
  assert.equal(compareQuarterMetric(pct("ebitda_margin_pct", 35.7), quarter(pct("ebitda_margin_pct", 0))).change, 35.7);
});
