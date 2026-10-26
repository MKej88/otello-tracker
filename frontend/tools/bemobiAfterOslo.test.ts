import assert from "node:assert/strict";
import { test } from "node:test";
import { displayedChange, displayedOtecEffect, displayedTheoreticalOtecPrice, displayedFxMovement, displayedCombinedTheoreticalPrice, movementChart, statusLabel } from "../src/bemobiAfterOsloModel.ts";

test("Missing, stale and failed refreshes never display a percentage", () => {
  assert.equal(displayedChange(null), null);
  assert.equal(displayedChange({ ready: false, status: "stale_quote", change_pct: 2 }), null);
  assert.equal(displayedChange({ ready: true, status: "ready", change_pct: NaN }), null);
  assert.equal(displayedChange({ ready: true, status: "ready", change_pct: 2 }, true), null);
  assert.equal(displayedChange({ ready: true, status: "ready", change_pct: 0 }), 0);
  assert.equal(displayedChange({ ready: true, status: "ready", change_pct: -2 }), -2);
  assert.match(statusLabel("missing_reference"), /Mangler kurs/);
});

test("Chart uses elapsed time and includes zero in positive and negative domains", () => {
  for (const delta of [2, -2, 0]) {
    const chart = movementChart([
      { at: "2026-10-05T14:25:00Z", change_pct: 0 },
      { at: "2026-10-05T14:40:00Z", change_pct: delta / 2 },
      { at: "2026-10-05T15:25:00Z", change_pct: delta },
    ]);
    assert.ok(chart);
    assert.ok(chart.zeroY >= 8 && chart.zeroY <= 92);
    assert.equal(Number(chart.line.split(" ")[1].split(",")[0]), 124);
    assert.doesNotMatch(chart.line, /NaN|Infinity/);
  }
  assert.equal(movementChart([]), null);
  assert.equal(movementChart([{ at: "invalid", change_pct: 0 }]), null);
});

test("Waiting for Oslo close suppresses Bemobi and OTEC values", () => {
  const data = { ready: false, status: "waiting_oslo_close", change_pct: 6.87,
    otec_effect: { ready: true, change_pct: 2, change_per_share_nok: .4, otec_price_nok: 20 } };
  assert.equal(statusLabel(data.status), "Venter på at Oslo Børs stenger");
  assert.equal(displayedChange(data), null);
  assert.equal(displayedOtecEffect(data), null);
  assert.equal(displayedTheoreticalOtecPrice(data), null);
});

test("OTEC effect shares the Bemobi freshness gate and requires finite results", () => {
  const data = { ready: true, status: "ready", change_pct: 2.4,
    otec_effect: { ready: true, change_pct: 1.52, change_per_share_nok: .3 } };
  assert.equal(displayedOtecEffect(data), data.otec_effect);
  assert.equal(displayedOtecEffect(data, true), null);
  assert.equal(displayedOtecEffect({ ...data, status: "stale_quote" }), null);
  assert.equal(displayedOtecEffect({ ...data, otec_effect: { ready: false } }), null);
  assert.equal(displayedOtecEffect({ ...data, otec_effect: { ...data.otec_effect, change_pct: Infinity } }), null);
  assert.equal(displayedOtecEffect({ ...data, otec_effect: { ...data.otec_effect, change_per_share_nok: NaN } }), null);
  assert.ok(displayedOtecEffect({ ...data, change_pct: 0, otec_effect: { ready: true, change_pct: 0, change_per_share_nok: 0 } }));
});

test("Theoretical OTEC price uses unrounded inputs and shares the freshness gate", () => {
  const data = { ready: true, status: "ready", change_pct: -.29,
    otec_effect: { ready: true, change_pct: -.42, change_per_share_nok: -.0849, otec_price_nok: 19.0049 } };
  assert.ok(Math.abs(displayedTheoreticalOtecPrice(data)! - 18.92) < 1e-10);
  assert.equal(displayedTheoreticalOtecPrice(data, true), null);
  assert.equal(displayedTheoreticalOtecPrice({ ...data, status: "stale_quote" }), null);
  assert.equal(displayedTheoreticalOtecPrice({ ...data, otec_effect: { ready: false } }), null);
  for (const close of [undefined, NaN, Infinity, 0, -1]) {
    assert.equal(displayedTheoreticalOtecPrice({ ...data, otec_effect: { ...data.otec_effect, otec_price_nok: close } }), null);
  }
  for (const delta of [NaN, Infinity, -20]) {
    assert.equal(displayedTheoreticalOtecPrice({ ...data, otec_effect: { ...data.otec_effect, change_per_share_nok: delta } }), null);
  }
  assert.equal(displayedTheoreticalOtecPrice({ ...data, otec_effect: { ...data.otec_effect, otec_price_nok: 19, change_per_share_nok: 0 } }), 19);
  assert.equal(displayedTheoreticalOtecPrice({ ...data, otec_effect: { ...data.otec_effect, otec_price_nok: 19, change_per_share_nok: .3 } }), 19.3);
});

test("Combined FX effect requires matching, valid reference and readable estimates", () => {
  const valid = {
    ready: true, status: "ready", change_pct: -4,
    otec_effect: { ready: true, change_pct: -5, change_per_share_nok: -1.1, otec_price_nok: 18.5,
      fx_movement: { ready: true, reference_rate: 1.7, latest_rate: 1.75, change_pct: 2.94,
        effect_per_share_nok: 0.2, combined_per_share_nok: -0.9, combined_pct_otec: -4.86,
        theoretical_otec_price_nok: 17.6 } },
  };
  assert.equal(displayedFxMovement(valid)?.combined_per_share_nok, -0.9);
  assert.equal(displayedCombinedTheoreticalPrice(valid), 17.6);
  assert.equal(displayedFxMovement({ ...valid, otec_effect: { ...valid.otec_effect, fx_movement: { ready: false } } }), null);
  assert.equal(displayedCombinedTheoreticalPrice({ ...valid, otec_effect: { ...valid.otec_effect, fx_movement: { ready: false } } }), null);
  assert.equal(displayedFxMovement(valid, true), null);
  assert.equal(displayedCombinedTheoreticalPrice(valid, true), null);
  assert.equal(displayedFxMovement({ ...valid, otec_effect: { ...valid.otec_effect,
    fx_movement: { ...valid.otec_effect.fx_movement, combined_pct_otec: Infinity } } }), null);
});
