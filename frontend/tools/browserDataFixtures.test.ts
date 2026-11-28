import assert from "node:assert/strict";
import test from "node:test";
import { richHistoryFixture, richBrazilFixture, fixtureOrigin, fixtureScript, HISTORY_PATH, BUYBACK_PATH, BRAZIL_PATH } from "./browser-data-fixtures.mjs";

test("synthetic history has coherent financial points and chart statistics", () => {
  const data = richHistoryFixture().estimated;
  assert.equal(data.ready, true);
  assert.equal(data.points.length, data.statistics.count);
  for (const point of data.points) assert.ok(Math.abs((1-point.otec_price/point.nav_per_share)*100-point.discount_pct)<1e-9);
  assert.equal(data.statistics.median_discount_pct, data.points[1].discount_pct);
});

test("synthetic Brazil fixture has all five indicators and two years of Focus estimates", () => {
  const data = richBrazilFixture();
  assert.equal(Object.keys(data.metrics).length, 5);
  for (const year of ["2026","2027"]) {
    for (const key of ["selic","ipca","gdp","usd_brl"]) assert.ok(Number.isFinite(data.focus.values[key][year].median));
    for (const key of ["selic","ipca","gdp"]) assert.ok(Number.isFinite(data.focus_trend.comparisons["30d"].points_by_year[year][key].change));
  }
});

test("fixture injection is limited to loopback and requires a ready buyback response", () => {
  assert.throws(() => fixtureOrigin("https://otellotracker.com/"), /lokal Worker/);
  assert.throws(() => fixtureScript("http://127.0.0.1:8787/",{ready:false}), /aktivt tilbakekjøpsprogram/);
  const script = fixtureScript("http://127.0.0.1:8787/", {ready:true,program:{}});
  assert.ok(script.includes(HISTORY_PATH));
  assert.ok(script.includes(BUYBACK_PATH));
  assert.ok(script.includes(BRAZIL_PATH));
  assert.doesNotThrow(() => new Function(script));
});
