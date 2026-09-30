import assert from "node:assert/strict";
import test from "node:test";

import { freshnessStatus } from "../src/dataFreshness.ts";
import { pageUpdateLabel } from "../src/pageUpdateFormat.ts";

test("nyhetssiden merker kildekontroll separat fra publiseringsdato", () => {
  const now = new Date("2026-09-30T11:00:00Z");
  assert.equal(pageUpdateLabel("2026-09-30T03:40:00Z", now, "Sist kontrollert"), "Sist kontrollert i dag kl. 05:40");
  assert.equal(pageUpdateLabel(null, now, "Sist kontrollert"), "Kontrolltidspunkt mangler");
});

test("viser i dag og i går etter kalenderen i Europe/Oslo", () => {
  const now = new Date("2026-09-27T22:30:00Z"); // 28. september i Oslo
  assert.equal(pageUpdateLabel("2026-09-27T16:05:00Z", now), "Oppdatert i går kl. 18:05");
  assert.equal(pageUpdateLabel("2026-09-28T12:32:00Z", now), "Oppdatert i dag kl. 14:32");
});

test("viser norsk dato og håndterer manglende tidspunkt nøytralt", () => {
  const now = new Date("2026-09-28T12:00:00Z");
  assert.equal(pageUpdateLabel("2026-09-25", now), "Oppdatert 25. september 2026");
  assert.equal(pageUpdateLabel(null, now), "Oppdateringstidspunkt mangler");
});

test("bruker den felles ferskhetsregelen for advarsel", () => {
  const now = new Date("2026-09-28T16:00:00Z");
  assert.equal(freshnessStatus("intraday", "2026-09-28T15:30:00Z", now) === "stale", false);
  assert.equal(freshnessStatus("intraday", "2026-09-25T10:00:00Z", now) === "stale", true);
});
