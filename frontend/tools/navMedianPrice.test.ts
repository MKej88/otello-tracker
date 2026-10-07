import assert from "node:assert/strict";
import test from "node:test";
import { medianDiscountPriceLine } from "../src/navMedianPrice.ts";
import { formatNumber } from "../src/uiFormat.ts";

const line = (nav: number | null | undefined, median: number | null | undefined, otec: number | null | undefined) =>
  medianDiscountPriceLine(nav, median, otec, formatNumber);

test("medianrabatt bruker eksisterende prosentverdi og norske formatteringer", () => {
  assert.equal(line(29.55, 22.8, 20), "Ved 1-års medianrabatt (22,8 %): 22,81 kr (+14,1 %)");
});

test("beregner oppside fra uavrundet teoretisk kurs", () => {
  // Rounding the price to 22.81 before division would display +14.1 instead.
  assert.equal(line(29.55, 22.81, 20), "Ved 1-års medianrabatt (22,8 %): 22,81 kr (+14,0 %)");
});

test("nedside har minustegn, mens null og avrundet null ikke har fortegn", () => {
  assert.equal(line(25, 25.04, 20), "Ved 1-års medianrabatt (25,0 %): 18,74 kr (−6,3 %)");
  assert.equal(line(25, 20, 20), "Ved 1-års medianrabatt (20,0 %): 20,00 kr (0,0 %)");
  assert.equal(line(25, 0, 20), "Ved 1-års medianrabatt (0,0 %): 25,00 kr (+25,0 %)");
  for (const nav of [20.001, 19.999]) {
    assert.equal(line(nav, 0, 20), "Ved 1-års medianrabatt (0,0 %): 20,00 kr (0,0 %)");
  }
});

test("manglende eller ugyldige data skjuler linjen uten NaN eller Infinity", () => {
  for (const value of [null, undefined, NaN, Infinity, -Infinity]) {
    assert.equal(line(value, 22.8, 20), null);
    assert.equal(line(29.55, value, 20), null);
    assert.equal(line(29.55, 22.8, value), null);
  }
  for (const value of [0, -1]) {
    assert.equal(line(value, 22.8, 20), null);
    assert.equal(line(29.55, 22.8, value), null);
  }
  assert.equal(line(29.55, 101, 20), null);
  assert.equal(line(29.55, 22.8, Number.MIN_VALUE), null);
  assert.equal(line(Number.MAX_VALUE, -Number.MAX_VALUE, 20), null);
});
