import assert from "node:assert/strict";
import test from "node:test";
import { rangePosition } from "../src/marketQuoteModel.ts";

test("52-ukersintervallet håndterer gyldige verdier og avgrenser posisjon", () => {
  assert.equal(rangePosition(15, 10, 20), 50);
  assert.equal(rangePosition(10, 10, 20), 0);
  assert.equal(rangePosition(20, 10, 20), 100);
  assert.equal(rangePosition(5, 10, 20), 0);
  assert.equal(rangePosition(25, 10, 20), 100);
  assert.equal(rangePosition(10, 10, 10), 50);
});

test("52-ukersintervallet avviser manglende, ikke-endelige og omvendte grenser", () => {
  assert.equal(rangePosition(null, 10, 20), null);
  assert.equal(rangePosition(15, undefined, 20), null);
  assert.equal(rangePosition(15, 10, null), null);
  assert.equal(rangePosition(NaN, 10, 20), null);
  assert.equal(rangePosition(15, -Infinity, 20), null);
  assert.equal(rangePosition(15, 10, Infinity), null);
  assert.equal(rangePosition(15, 20, 10), null);
});
