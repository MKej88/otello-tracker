import assert from "node:assert/strict";
import test from "node:test";
import { formatCompanyEventTitle, formatNumber } from "../src/uiFormat.ts";

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


test("kalender normaliserer eldre Bemobi-titler uten å endre andre hendelser", () => {
  assert.equal(formatCompanyEventTitle("Betalingsdato for JCP", "Bemobi"), "Utbetaling av renter på egenkapital");
  assert.equal(formatCompanyEventTitle("Ex-dato for JCP", "Bemobi"), "Ex-dato for renter på egenkapital");
  assert.equal(formatCompanyEventTitle("Utbetaling av renter på egenkapital", "Bemobi"), "Utbetaling av renter på egenkapital");
  assert.equal(formatCompanyEventTitle("Betalingsdato for utbytte", "Bemobi"), "Betalingsdato for utbytte");
  assert.equal(formatCompanyEventTitle("Betalingsdato for JCP", "Otello"), "Betalingsdato for JCP");
});
