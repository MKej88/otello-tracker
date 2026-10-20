import test from "node:test";
import assert from "node:assert/strict";
import {
  classifyColdFailure, createApiDiagnostics, httpCategory, probeColdWithRetry,
} from "./performance-diagnostics.mjs";

const origin = "https://otellotracker.com";

test("Chrome HTTP errors are categorized without query strings, headers or third-party requests", () => {
  const trace = createApiDiagnostics(origin);
  trace.onEvent("Network.requestWillBeSent", {
    requestId: "1", request: {
      url: origin + "/api/dashboard/summary?token=secret&user=alice",
      headers: { Authorization: "sensitive" },
    },
  });
  trace.onEvent("Network.responseReceived", {
    requestId: "1", response: { status: 429, url: origin + "/api/dashboard/summary?token=secret" },
  });
  trace.onEvent("Network.loadingFinished", { requestId: "1" });
  trace.onEvent("Network.requestWillBeSent", {
    requestId: "2", request: { url: "https://other.example/api/forbidden?secret=true" },
  });
  trace.onEvent("Network.responseReceived", { requestId: "2", response: { status: 503 } });
  assert.deepEqual(trace.snapshot(), {
    apiIssues: [{ path: "/api/dashboard/summary", status: 429, category: "rate_limited" }],
    pendingApiPaths: [],
  });
  assert.doesNotMatch(JSON.stringify(trace.snapshot()), /secret|Authorization|alice|other.example/);
  assert.equal(httpCategory(503), "server_http_error");
  assert.equal(httpCategory(404), "client_http_error");
});

test("Network transport failure is reduced to safe coarse categories", () => {
  const trace = createApiDiagnostics(origin);
  trace.onEvent("Network.requestWillBeSent", {
    requestId: "3", request: { url: origin + "/api/fx/dashboard?private=ignore" },
  });
  assert.deepEqual(trace.snapshot().pendingApiPaths, ["/api/fx/dashboard"]);
  trace.onEvent("Network.loadingFailed", {
    requestId: "3", errorText: "net::ERR_NAME_NOT_RESOLVED /private/detail",
  });
  assert.deepEqual(trace.snapshot(), {
    apiIssues: [{ path: "/api/fx/dashboard", status: null, category: "dns" }],
    pendingApiPaths: [],
  });
});

test("A missing dataset is not mislabeled as a slow page", () => {
  const data = classifyColdFailure(
    new Error("No valid main content within 25000ms"),
    { unavailable: true, markerFound: false, loading: false, headingMatches: true },
    { apiIssues: [], pendingApiPaths: [] },
  );
  assert.equal(data.category, "data_unavailable");
  assert.equal(data.page.headingMatches, true);
  const loading = classifyColdFailure(
    new Error("No valid main content within 25000ms"),
    { unavailable: false, loading: true },
    { apiIssues: [], pendingApiPaths: ["/api/fx/dashboard"] },
  );
  assert.equal(loading.category, "data_load_timeout");
  assert.deepEqual(loading.pendingApiPaths, ["/api/fx/dashboard"]);
});

test("HTTP response takes precedence over a generic application data error", () => {
  const info = classifyColdFailure(
    new Error("Investor data error on #bemobi"),
    { error: true, unavailable: true },
    { apiIssues: [{ path: "/api/bemobi/dashboard", status: 502, category: "server_http_error" }], pendingApiPaths: [] },
  );
  assert.equal(info.category, "server_http_error");
  assert.equal(info.apiIssues[0].status, 502);
});

test("Healthy cold load is measured once", async () => {
  let starts = 0;
  const result = await probeColdWithRetry(async () => { starts++; return { firstDataMs: 312 }; });
  assert.equal(starts, 1);
  assert.equal(result.ok, true);
  assert.deepEqual(result.attempts, [{ attempt: 1, outcome: "success", firstDataMs: 312 }]);
});

test("A transient first cold-load failure remains visible after a successful retry", async () => {
  let starts = 0;
  let waits = 0;
  const result = await probeColdWithRetry(async () => {
    starts++;
    if (starts === 1) {
      const error = new Error("network");
      error.diagnosis = classifyColdFailure(
        error, { error: true }, {
          apiIssues: [{ path: "/api/bemobi/dashboard", status: 503, category: "server_http_error" }],
          pendingApiPaths: [],
        },
      );
      throw error;
    }
    return { firstDataMs: 490 };
  }, async () => { waits++; });
  assert.equal(result.ok, true);
  assert.equal(starts, 2);
  assert.equal(waits, 1);
  assert.equal(result.attempts.length, 2);
  assert.equal(result.attempts[0].diagnosis.category, "server_http_error");
  assert.equal(result.attempts[1].firstDataMs, 490);
});

test("Two persistent failures remain failures with both diagnostic snapshots", async () => {
  let starts = 0;
  const result = await probeColdWithRetry(async () => {
    starts++;
    const error = new Error("No valid main content within 25000ms");
    error.diagnosis = classifyColdFailure(error, { loading: true }, {
      apiIssues: [], pendingApiPaths: ["/api/fx/dashboard"],
    });
    throw error;
  });
  assert.equal(result.ok, false);
  assert.equal(starts, 2);
  assert.deepEqual(result.attempts.map((a) => a.diagnosis.category), [
    "data_load_timeout", "data_load_timeout",
  ]);
  assert.equal(result.attempts[0].diagnosis.pendingApiPaths[0], "/api/fx/dashboard");
});
