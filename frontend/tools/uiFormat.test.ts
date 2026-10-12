import assert from "node:assert/strict";
import test from "node:test";
import { formatNumber } from "../src/uiFormat.ts";

test("tallformat bevarer norsk visning, avrunding og manglende verdier", () => {
  assert.equal(formatNumber(1234.5), "1\u00a0234,50");
  assert.equal(formatNumber(-1234.5, 1), "−1\u00a0234,5");
  for (const value of [null, undefined, NaN, Infinity, -Infinity]) {
    assert.equal(formatNumber(value), "–");
  }

  // Sammenlign med tidligere formattering, også når presisjoner og tall skifter.
  const values = [0, -0, 0.005, -0.005, 1.005, -1.005, 999.995,
    Number.MIN_VALUE, Number.MAX_VALUE, Number.MAX_SAFE_INTEGER];
  for (let index = -1000; index <= 1000; index++) values.push(index / 7);
  for (const digits of [2, 0, 4, 1, 3, 2]) {
    for (const value of values) {
      assert.equal(formatNumber(value, digits), value.toLocaleString("nb-NO", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }));
    }
  }
  assert.throws(() => formatNumber(1, -1), RangeError);
  assert.throws(() => formatNumber(1, Infinity), RangeError);
});
