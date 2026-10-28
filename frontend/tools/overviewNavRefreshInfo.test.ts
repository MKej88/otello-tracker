import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const overview = readFileSync(new URL("../src/OverviewPage.tsx", import.meta.url), "utf8");

test("NAV timestamp says calculated rather than implying live prices", () => {
  assert.match(overview, /NAV sist beregnet \{updatedTimeLabel\(nav\?\.calculated_at\)\}/);
  assert.doesNotMatch(overview, /NAV oppdatert/);
});

test("NAV card shows concise, combined delayed-price information", () => {
  assert.match(overview, /Kurser og oppdatering/);
  assert.match(overview, /NAV beregnes normalt hvert 30\. minutt med siste tilgjengelige data/);
  assert.match(overview, /Aksjekurser:/);
  assert.match(overview, /Otello og Bemobi vises med forsinkede kurser \(normalt ca\. 15 minutter\)/);
  assert.doesNotMatch(overview, /Kurser er ikke i sanntid/);
  assert.doesNotMatch(overview, /Euronext-kursene er forsinket/);
  assert.doesNotMatch(overview, /B3-kurser er normalt minst/);
});

test("BRL/NOK shows one up-to-date value and offers source-aware fallbacks", () => {
  assert.match(overview, /usePollingResource<CurrentFxPayload>\(\s*"\/api\/fx\/dashboard"/);
  assert.match(overview, /const currentFxTime = fxObservationTime\(fxSpot\?\.observed_at\)/);
  assert.match(overview, /<b>BRL\/NOK:<\/b> \{formatNumber\(fxSpot\.brl_nok!, 4\)\} · Oppdatert \{currentFxTime\}/);
  assert.match(overview, /Kursen er videreført fra siste registrerte handel/);
  assert.match(overview, /nyere markedskurs ikke tilgjengelig/);
  assert.match(overview, /Norges Banks referansekurs \(bankdager\)/);
  assert.match(overview, /Dagens kurs \{shownBrlNok == null/);
  assert.match(overview, /current=\{shownBrlNok\}/);
  assert.doesNotMatch(overview, /BRL\/NOK i sist beregnede NAV:/);
  assert.doesNotMatch(overview, /Siste tilgjengelige markedskurs fra Exchangerate\.dev/);
  assert.doesNotMatch(overview, /Rates by Exchangerate\.dev/);
});
