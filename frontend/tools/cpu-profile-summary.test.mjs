import test from "node:test";
import assert from "node:assert/strict";
import { summarizeCpuProfile } from "./cpu-profile-summary.mjs";

test("only same-origin JS function samples are reported; queries and third parties disappear", () => {
  const report = summarizeCpuProfile({
    nodes: [
      { id: 1, callFrame: { url: "https://otellotracker.com/assets/app.js?token=private", functionName: "render" } },
      { id: 2, callFrame: { url: "https://other.invalid/spy.js", functionName: "secret" } },
      { id: 3, callFrame: { url: "", functionName: "(idle)" } },
    ],
    samples: [1, 2, 1, 3],
    timeDeltas: [2000, 900, 3000, 1500],
  }, "https://otellotracker.com");
  assert.equal(report.totalSamples, 4);
  assert.equal(report.attributedSamples, 2);
  assert.deepEqual(report.topFunctions, [
    { path: "/assets/app.js", functionName: "render", samples: 2, estimatedCpuMs: 5 },
  ]);
  assert.doesNotMatch(JSON.stringify(report), /private|spy|other.invalid|secret/);
});

test("missing samples and malformed URLs produce an empty, bounded summary", () => {
  assert.deepEqual(summarizeCpuProfile({}, "https://otellotracker.com"), {
    totalSamples: 0, attributedSamples: 0, topFunctions: [],
  });
});
