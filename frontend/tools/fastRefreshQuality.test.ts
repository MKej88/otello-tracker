import assert from "node:assert/strict";
import { test } from "node:test";
import { fastRefreshIssue } from "../src/fastRefreshQuality.ts";

test("confirmed translation warning is not a market error or last-good timestamp", () => {
  const issue = fastRefreshIssue({status:"PARTIAL", has_error:true, finished_at:"2026-11-27T11:31:00Z",
    secondary_warning:{steps:["bemobi_translation"], translation_queue:{failed:9, exhausted:1, overdue:1, failed_this_run:1}}});
  assert.equal(issue?.badgeLabel, "ADVARSEL");
  assert.equal(issue?.affects, "Norske Bemobi-dokumenter");
  assert.match(issue?.detail ?? "", /9 dokumenter med feil/);
  assert.equal(issue?.lastRun, "2026-11-27T11:31:00Z");
  assert.ok(!("lastGood" in (issue ?? {})));
});

test("unknown or stale failures cannot be downgraded", () => {
  assert.equal(fastRefreshIssue({status:"PARTIAL", secondary_warning:{steps:["dirty_nav"]}})?.id, "fast-refresh-error");
  assert.equal(fastRefreshIssue({status:"PARTIAL", stale:true, secondary_warning:{steps:["bemobi_translation"]}})?.id, "fast-refresh-stale");
  assert.equal(fastRefreshIssue({status:"SUCCESS"}), null);
});
