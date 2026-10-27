import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const overview = readFileSync(new URL("../src/OverviewPage.tsx", import.meta.url), "utf8");

test("NAV timestamp says calculated rather than implying live prices", () => {
  assert.match(overview, /NAV sist beregnet \{updatedTimeLabel\(nav\?\.calculated_at\)\}/);
  assert.doesNotMatch(overview, /NAV oppdatert/);
});

test("NAV card explains update frequency and non-live market data", () => {
  assert.match(overview, /Kurser er ikke i sanntid/);
  assert.match(overview, /hvert 30\. minutt/);
  assert.match(overview, /Otello \(OTEC\)/);
  assert.match(overview, /Euronext-kursene er forsinket med opptil 15 minutter/);
  assert.match(overview, /Bemobi \(BMOB3\)/);
  assert.match(overview, /15 minutter forsinket/);
  assert.match(overview, /BRL\/NOK/);
  assert.match(overview, /én ny kurs per bankdag/);
});

test("BRL/NOK uses plain-language update timing without duplicate provider credit", () => {
  assert.match(overview, /Siste tilgjengelige markedskurs fra Exchangerate\.dev/);
  assert.match(overview, /Registrert/);
  // Spot text must use the market FX endpoint, never the NAV snapshot timestamp.
  assert.match(overview, /usePollingResource<CurrentFxPayload>\(\s*"\/api\/fx\/dashboard"/);
  assert.match(overview, /const currentFxTime = fxObservationTime\(fxSpot\?\.observed_at\)/);
  assert.match(overview, /BRL\/NOK i sist beregnede NAV:/);
  assert.match(overview, /Dagens kurs \{shownBrlNok == null/);
  assert.match(overview, /current=\{shownBrlNok\}/);
  assert.match(overview, /kontrolleres hvert 30\. minutt/);
  assert.doesNotMatch(overview, /Indikativ markedskurs/);
  assert.doesNotMatch(overview, /Rates by Exchangerate\.dev/);
});
