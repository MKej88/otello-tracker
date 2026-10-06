import assert from "node:assert/strict";
import { test } from "node:test";
import { displayedChange, displayedOtecEffect, movementChart, statusLabel } from "../src/bemobiAfterOsloModel.ts";

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
