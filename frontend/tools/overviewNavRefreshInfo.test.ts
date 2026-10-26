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
  assert.match(overview, /Bemobi \(BMOB3\)/);
  assert.match(overview, /15 minutter forsinket/);
  assert.match(overview, /BRL\/NOK/);
  assert.match(overview, /én ny kurs per bankdag/);
});

test("BRL/NOK uses plain-language update timing without duplicate provider credit", () => {
  assert.match(overview, /Oppdateres hvert 30\\. minutt\\. Kursen er ca\\. 15 minutter forsinket\\./);
  assert.doesNotMatch(overview, /Indikativ markedskurs/);
  assert.doesNotMatch(overview, /Rates by Exchangerate\\.dev/);
});
