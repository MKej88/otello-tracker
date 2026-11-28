import test from "node:test";
import assert from "node:assert/strict";
import { cachedDateTimeFormatter, formatDateTime, formatInteger } from "../src/uiFormat.ts";

test("Gjenbruker datoformattering uten å blande tidssoner, språk eller valg", () => {
  const options = { timeZone: "Europe/Oslo", hour: "2-digit", minute: "2-digit", hour12: false } as const;
  const first = cachedDateTimeFormatter("nb-NO", options);
  assert.equal(first, cachedDateTimeFormatter("nb-NO", { ...options }));
  assert.notEqual(first, cachedDateTimeFormatter("nb-NO", { ...options, timeZone: "UTC" }));
  assert.notEqual(first, cachedDateTimeFormatter("en-GB", options));
  for (const day of ["2026-03-29T01:30:00Z", "2026-10-25T01:30:00Z", "2026-11-28T12:00:00Z"]) {
    assert.equal(first.format(new Date(day)), new Intl.DateTimeFormat("nb-NO", options).format(new Date(day)));
  }
});

test("Norsk dato, klokkeslett og heltall beholder tidligere visning", () => {
  const instant = new Date("2026-11-28T12:05:00Z");
  const date = instant.toLocaleDateString("nb-NO", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Oslo" });
  const time = instant.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Oslo" });
  assert.equal(formatDateTime(instant), `${date} kl. ${time}`);
  assert.equal(formatDateTime("ugyldig"), "ugyldig");
  for (const n of [0, -0.1, 1.5, -2.7, 1234567.6]) assert.equal(formatInteger(n), Math.round(n).toLocaleString("nb-NO"));
});
