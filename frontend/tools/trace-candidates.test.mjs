import test from "node:test";
import assert from "node:assert/strict";
import { slowTraceCandidates } from "./trace-candidates.mjs";

test("slow origin misses retain only bounded searchable Cloudflare ray ids", () => {
  const rows = slowTraceCandidates([
    {
      endpoint: "/api/bemobi/consensus?key=should-never-print",
      sampleTotalMs: [1820, 52, 1499],
      cfRay: ["a1b2c3d4e5f67890-DFW", "abcdef0123456789-DFW", "bad"],
      cfCacheStatus: ["MISS", "HIT", "HIT"],
      sampleStartedAt: ["2026-10-29T15:20:00.123Z", "2026-10-29T15:20:01.123Z", null],
    },
  ]);
  assert.deepEqual(rows, [{
    path: "/api/bemobi/consensus",
    elapsedMs: 1820,
    utc: "2026-10-29T15:20:00.123Z",
    rayId: "a1b2c3d4e5f67890",
    colo: "DFW",
    cache: "MISS",
  }]);
  assert.doesNotMatch(JSON.stringify(rows), /should-never-print|abcdef0123456789/);
});

test("invalid ray and time remain unavailable rather than exposing unsafe values", () => {
  const rows = slowTraceCandidates([
    {
      endpoint: "/api/health",
      sampleTotalMs: [1523],
      cfRay: ['secret; Authorization:token'],
      cfCacheStatus: ["INVENTED"],
      sampleStartedAt: ["bad time"],
    },
    {
      endpoint: "/another/location?secret=1",
      sampleTotalMs: [99999],
      cfRay: ["a1b2c3d4e5f67890-IAD"],
      sampleStartedAt: ["2026-10-29T15:20:00.123Z"],
    },
  ]);
  assert.deepEqual(rows, [{
    path: "/api/health",
    elapsedMs: 1523,
    utc: null,
    rayId: null,
    colo: null,
    cache: "unknown",
  }]);
  assert.doesNotMatch(JSON.stringify(rows), /token|secret|another/);
});

test("no candidate for fast or missing measurements", () => {
  assert.deepEqual(slowTraceCandidates([]), []);
  assert.deepEqual(slowTraceCandidates([{ endpoint: "/api/health", sampleTotalMs: [40, NaN] }]), []);
});
