import assert from "node:assert/strict";
import test from "node:test";
import { navUpsideLine } from "../src/navUpside.ts";
import { formatNumber } from "../src/uiFormat.ts";

const line = (nav: number | null | undefined, otec: number | null | undefined) =>
  navUpsideLine(nav, otec, formatNumber);

test("oppside beregnes fra aksjekursen, ikke som NAV-rabatten", () => {
  assert.equal(line(32.56, 21.15), "+11,41 kr (+53,9 %)");
  assert.equal(line(30, 20), "+10,00 kr (+50,0 %)");
});

test("prosenten bruker uavrundet NAV og kurs", () => {
  assert.equal(line(29.547, 20), "+9,55 kr (+47,7 %)");
});

test("overkurs viser negativ avstand, og avrundet null har ikke fortegn", () => {
  assert.equal(line(15, 20), "−5,00 kr (−25,0 %)");
  assert.equal(line(20, 20), "0,00 kr (0,0 %)");
  for (const nav of [20.001, 19.999]) {
    assert.equal(line(nav, 20), "0,00 kr (0,0 %)");
  }
});

test("manglende, ugyldige eller ikke-positive verdier gir ingen oppside", () => {
  for (const value of [null, undefined, NaN, Infinity, -Infinity, 0, -1]) {
    assert.equal(line(value, 20), null);
    assert.equal(line(30, value), null);
  }
  assert.equal(line(30, Number.MIN_VALUE), null);
});
