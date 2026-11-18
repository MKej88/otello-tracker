import assert from "node:assert/strict";
import test from "node:test";
import { kpiResultPeriod, resolveAdjustedEbitdaMargin } from "../src/bemobiKpiMetrics.ts";

test("viser rapportens margin og kvartal når disse er oppgitt", () => {
  const result = {
    period: "3Q26",
    adjusted_ebitda_margin_pct: 35.4,
    adjusted_net_revenue_mbrl: 245,
    adjusted_ebitda_mbrl: 87,
  };
  assert.equal(kpiResultPeriod(result), "3Q26");
  assert.deepEqual(resolveAdjustedEbitdaMargin(result), { value: 35.4, basis: "reported" });
});

test("manglende margin beregnes tydelig fra samme kvartals EBITDA og omsetning", () => {
  const result = {
    period: "3Q26",
    adjusted_ebitda_margin_pct: null,
    adjusted_net_revenue_mbrl: 245,
    adjusted_ebitda_mbrl: 87,
  };
  const margin = resolveAdjustedEbitdaMargin(result);
  assert.equal(margin.basis, "calculated");
  assert.ok(Math.abs(margin.value! - 87 / 245 * 100) < 1e-10);
  assert.equal(margin.value!.toLocaleString("nb-NO", { minimumFractionDigits: 1, maximumFractionDigits: 1 }), "35,5");
  assert.equal(kpiResultPeriod(result), "3Q26");
});

test("manglende eller ugyldige EBITDA-verdier gir ikke oppdiktet margin", () => {
  for (const item of [
    null, {}, { adjusted_ebitda_mbrl: 87 },
    { adjusted_net_revenue_mbrl: 0, adjusted_ebitda_mbrl: 87 },
    { adjusted_net_revenue_mbrl: 245, adjusted_ebitda_mbrl: NaN },
    { adjusted_net_revenue_mbrl: 245, adjusted_ebitda_mbrl: 300 },
    { adjusted_net_revenue_mbrl: 245, adjusted_ebitda_mbrl: -2 },
  ]) {
    assert.deepEqual(resolveAdjustedEbitdaMargin(item), { value: null, basis: "missing" });
  }
  assert.equal(kpiResultPeriod(null), "Periode ukjent");
});

test("registrert 0% margin er et gyldig rapportert tall", () => {
  assert.deepEqual(
    resolveAdjustedEbitdaMargin({ adjusted_ebitda_margin_pct: 0 }),
    { value: 0, basis: "reported" },
  );
});

test("avvikende rapportert margin faller tilbake til beregning uten falsk rapportert-status", () => {
  assert.equal(resolveAdjustedEbitdaMargin({
    adjusted_ebitda_margin_pct: 140,
    adjusted_net_revenue_mbrl: 200,
    adjusted_ebitda_mbrl: 60,
  }).basis, "calculated");
});
