import assert from "node:assert/strict";
import test from "node:test";

import {
  analyzeFxDrivers,
  movementText,
  roundedContributions,
} from "../src/fxDriverAnalysis.ts";

test("tolker sterkere og svakere NOK og BRL i naturlig språk", () => {
  const stronger = analyzeFxDrivers(-2.2, -0.1)!;
  assert.equal(stronger.nokDirection, "sterkere");
  assert.equal(stronger.brlDirection, "sterkere");
  assert.match(movementText("NOK", stronger.nokDirection, -2.2, String), /NOK styrket seg 2.2/);

  const weaker = analyzeFxDrivers(1.5, 0.6)!;
  assert.equal(weaker.nokDirection, "svakere");
  assert.equal(weaker.brlDirection, "svakere");
  assert.match(movementText("BRL", weaker.brlDirection, 0.6, String), /BRL svekket seg 0.6/);
});

test("beregner riktig retning og eksakte bidrag til BRL/NOK", () => {
  const negative = analyzeFxDrivers(-2.2, -0.1)!;
  assert.ok(negative.totalPct < 0);
  assert.ok(negative.nokContribution < 0);
  assert.ok(negative.brlContribution > 0);
  assert.ok(Math.abs(negative.nokContribution + negative.brlContribution - negative.totalPct) < 1e-10);

  const positive = analyzeFxDrivers(1.5, 0.6)!;
  assert.ok(positive.totalPct > 0);
});

test("velger hoveddriver og kan rapportere omtrent like bidrag", () => {
  assert.equal(analyzeFxDrivers(-2.2, -0.1)!.mainDriver, "NOK");
  assert.equal(analyzeFxDrivers(-0.2, -2.0)!.mainDriver, "BRL");
  assert.equal(analyzeFxDrivers(1, -1)!.mainDriver, null);
});

test("avrunding lar driverbidragene summere til vist netto", () => {
  const rounded = roundedContributions(analyzeFxDrivers(-2.24, -0.14)!);
  assert.equal(rounded.nok + rounded.brl, rounded.total);
  assert.deepEqual(rounded, { nok: -2.2, brl: 0.1, total: -2.1 });
});

test("samme analyse støtter både 1M- og YTD-periodedata", () => {
  const periods = {
    m1: analyzeFxDrivers(-2.2, -0.1),
    ytd: analyzeFxDrivers(3.1, 1.0),
  };
  assert.ok(periods.m1!.totalPct < 0);
  assert.ok(periods.ytd!.totalPct > 0);
});
