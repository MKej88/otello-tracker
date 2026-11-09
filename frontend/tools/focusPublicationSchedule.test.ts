import assert from "node:assert/strict";
import { test } from "node:test";
import { focusPublicationDates } from "../src/focusPublicationSchedule.ts";

test("Focus 30 October was published after the Brazilian 2 November holiday", () => {
  assert.deepEqual(focusPublicationDates("2026-10-30", "2026-11-09"), {
    publishedDate: "2026-11-03",
    nextExpectedDate: "2026-11-09",
  });
});

test("Do not claim that a same-day scheduled Focus report has already been published", () => {
  assert.deepEqual(focusPublicationDates("2026-11-06", "2026-11-09"), {
    publishedDate: null,
    nextExpectedDate: "2026-11-09",
  });
  assert.deepEqual(focusPublicationDates("2026-11-06", "2026-11-10"), {
    publishedDate: "2026-11-09",
    nextExpectedDate: "2026-11-16",
  });
});

test("National holidays move the usual Monday Focus release to Tuesday", () => {
  assert.deepEqual(focusPublicationDates("2026-10-09", "2026-10-14"), {
    publishedDate: "2026-10-13",
    nextExpectedDate: "2026-10-19",
  });
  assert.deepEqual(focusPublicationDates("2026-09-04", "2026-09-10"), {
    publishedDate: "2026-09-08",
    nextExpectedDate: "2026-09-14",
  });
});

test("Outdated snapshots still display the next scheduled publication, not a past date", () => {
  assert.deepEqual(focusPublicationDates("2026-10-30", "2026-11-17"), {
    publishedDate: "2026-11-03",
    nextExpectedDate: "2026-11-23",
  });
});

test("Missing or malformed dates cannot produce misleading publication labels", () => {
  assert.deepEqual(focusPublicationDates(undefined, "2026-11-09"), {
    publishedDate: null,
    nextExpectedDate: null,
  });
  assert.deepEqual(focusPublicationDates("2026-02-30", "2026-11-09"), {
    publishedDate: null,
    nextExpectedDate: null,
  });
  assert.deepEqual(focusPublicationDates("2026-10-30", ""), {
    publishedDate: null,
    nextExpectedDate: null,
  });
});
