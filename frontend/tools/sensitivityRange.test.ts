import assert from "node:assert/strict";
import test from "node:test";
import { historicalScenarioRange } from "../src/sensitivityRange.ts";

test("spans historical endpoints without rounding to a fixed market interval", () => {
  const values = historicalScenarioRange(1.7345, 2.1234, 1.91, 7);
  assert.equal(values.length, 7);
  assert.equal(values[0], 1.7345);
  assert.equal(values[6], 2.1234);
  assert.ok(values.every((value, index) => index === 0 || value > values[index - 1]));
});
test("updates as historical extrema change and includes new market extremes", () => {
  assert.equal(historicalScenarioRange(1.8, 2, 2.2, 7).at(-1), 2.2);
  assert.equal(historicalScenarioRange(1.8, 2, 1.7, 7)[0], 1.7);
  assert.notDeepEqual(historicalScenarioRange(1.8, 2, 1.9, 7), historicalScenarioRange(1.85, 2, 1.9, 7));
});
test("unusable historical data requests a fallback", () => {
  for (const low of [null, undefined, NaN, Infinity, 0, -1, 2.1]) {
    assert.deepEqual(historicalScenarioRange(low, 2, 1.9, 7), []);
  }
  assert.deepEqual(historicalScenarioRange(2, 2, 2, 7), []);
});
