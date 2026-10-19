import assert from "node:assert/strict";
import test from "node:test";
import {
  slowestApiResources,
  summarizeFirstScreen,
  type FirstScreenSample,
} from "../src/firstScreenPerformance.ts";

function sample(route: FirstScreenSample["route"], ms: number, ttfb: number): FirstScreenSample {
  return {
    route,
    recordedAt: "2026-10-19T10:00:00.000Z",
    firstDataMs: ms,
    ttfbMs: ttfb,
    domReadyMs: 300,
    slowApi: [],
  };
}

test("beregner median og p95 separat per direkte åpnet side", () => {
  const samples = [
    sample("Oversikt", 1000, 200),
    sample("Brasil", 4000, 300),
    sample("Oversikt", 2500, 700),
    sample("Oversikt", 1500, 400),
    sample("Oversikt", 1800, 500),
  ];

  const overview = summarizeFirstScreen(samples, "Oversikt");
  assert.equal(overview.count, 4);
  assert.equal(overview.medianMs, 1500);
  assert.equal(overview.p95Ms, 2500);
  assert.equal(overview.medianTtfbMs, 400);
  assert.equal(overview.latest?.firstDataMs, 1800);
  assert.equal(summarizeFirstScreen(samples, "Brasil").medianMs, 4000);
  assert.equal(summarizeFirstScreen([], "Brasil").medianMs, null);
});

test("lagrer kun egne API-stier uten domenenavn eller query", () => {
  const resources = [
    { name: "https://otellotracker.com/api/dashboard/economic?secret=discard", duration: 350 },
    { name: "https://otellotracker.com/api/brazil/dashboard", duration: 810 },
    { name: "https://other.example/api/dashboard/summary", duration: 2000 },
    { name: "https://otellotracker.com/private", duration: 900 },
    { name: "broken url", duration: 10 },
  ];
  assert.deepEqual(slowestApiResources(resources, "https://otellotracker.com"), [
    { path: "/api/brazil/dashboard", durationMs: 810 },
    { path: "/api/dashboard/economic", durationMs: 350 },
  ]);
});

test("utelater ugyldig varighet fra ytelsesmålinger", () => {
  const resources = [
    { name: "https://otellotracker.com/api/valid", duration: 2.8 },
    { name: "https://otellotracker.com/api/broken", duration: Number.NaN },
  ];
  assert.deepEqual(slowestApiResources(resources, "https://otellotracker.com"), [
    { path: "/api/valid", durationMs: 3 },
  ]);
});
