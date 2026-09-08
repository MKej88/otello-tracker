import assert from "node:assert/strict";
import test from "node:test";

import { percentileAssessment } from "../src/percentileAssessment.ts";

const period = "3M";

test("klassifiserer representative persentiler med label og forklaring", () => {
  const cases = [
    [5, "Svært lav rabatt", "Rabatten er blant de 10 % laveste i perioden 3M."],
    [19, "Lav historisk rabatt", "Bare 19 % av observasjonene i perioden 3M har hatt lavere rabatt."],
    [30, "Under normalen", "Rabatten er lavere enn normalt i perioden 3M."],
    [50, "Rundt normalen", "Rabatten ligger omtrent midt i det historiske intervallet for perioden 3M."],
    [68, "Over normalen", "Rabatten er høyere enn normalt i perioden 3M."],
    [87, "Høy historisk rabatt", "Bare 13 % av observasjonene i perioden 3M har hatt høyere rabatt."],
    [96, "Svært høy rabatt", "Rabatten er blant de 10 % høyeste i perioden 3M."],
  ] as const;

  for (const [value, label, explanation] of cases) {
    assert.deepEqual(percentileAssessment(value, period), { label, explanation });
  }
});

test("håndterer alle terskelverdier konsekvent", () => {
  assert.equal(percentileAssessment(0, period).label, "Svært lav rabatt");
  assert.equal(percentileAssessment(10, period).label, "Svært lav rabatt");
  assert.equal(percentileAssessment(25, period).label, "Lav historisk rabatt");
  assert.equal(percentileAssessment(40, period).label, "Under normalen");
  assert.equal(percentileAssessment(60, period).label, "Rundt normalen");
  assert.equal(percentileAssessment(75, period).label, "Over normalen");
  assert.equal(percentileAssessment(90, period).label, "Høy historisk rabatt");
  assert.equal(percentileAssessment(100, period).label, "Svært høy rabatt");
});

test("viser en trygg forklaring ved manglende eller ugyldig verdi", () => {
  const expected = {
    label: "Historisk plassering mangler",
    explanation: "Kan ikke vurderes for perioden 3M.",
  };

  assert.deepEqual(percentileAssessment(null, period), expected);
  assert.deepEqual(percentileAssessment(undefined, period), expected);
  assert.deepEqual(percentileAssessment(Number.NaN, period), expected);
  assert.deepEqual(percentileAssessment(-1, period), expected);
  assert.deepEqual(percentileAssessment(101, period), expected);
});
