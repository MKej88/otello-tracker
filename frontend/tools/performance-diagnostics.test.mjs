import test from "node:test";
import assert from "node:assert/strict";
import {
  classifyColdFailure, createApiDiagnostics, fetchWithRateLimitRetry, httpCategory,
  isRateLimitError, isTimeoutError, parseHealthD1Timing, parseRetryAfterMs, probeColdWithRetry, retryOnTimeout,
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

test("Retry-After seconds, HTTP dates and malformed headers are handled safely", () => {
  assert.equal(parseRetryAfterMs("3"), 3000);
  assert.equal(parseRetryAfterMs("2.5"), 2500);
  assert.equal(parseRetryAfterMs("Wed, 21 Oct 2026 12:00:05 GMT", Date.parse("2026-10-21T12:00:00Z")), 5000);
  assert.equal(parseRetryAfterMs("nonsense"), null);
  assert.equal(parseRetryAfterMs("-4"), null);
  assert.equal(parseRetryAfterMs(null), null);
});

test("A 429 is retried with Retry-After without contaminating measured fetch timing", async () => {
  const waits = [];
  let calls = 0;
  const result = await fetchWithRateLimitRetry("https://otellotracker.com/api/test", {
    fetchFn: async () => {
      calls++;
      return calls === 1
        ? new Response(null, { status: 429, headers: { "retry-after": "2" } })
        : new Response("{}", { status: 200 });
    },
    sleepFn: async (ms) => { waits.push(ms); },
  });
  assert.equal(calls, 2);
  assert.deepEqual(waits, [2000]);
  assert.equal(result.response.status, 200);
  assert.equal(result.rateLimitedAttempts, 1);
});

test("Persistent 429s are classified as rate limiting rather than app failures", async () => {
  let calls = 0;
  const waits = [];
  await assert.rejects(
    () => fetchWithRateLimitRetry("https://otellotracker.com/api/test", {
      fetchFn: async () => {
        calls++;
        return new Response(null, { status: 429 });
      },
      sleepFn: async (ms) => { waits.push(ms); },
    }),
    (error) => isRateLimitError(error) && error.rateLimitedAttempts === 3,
  );
  assert.equal(calls, 3);
  assert.deepEqual(waits, [5000, 10000]);
});

test("Long Retry-After is respected by skipping the retry", async () => {
  let calls = 0;
  await assert.rejects(
    () => fetchWithRateLimitRetry("https://otellotracker.com/api/test", {
      fetchFn: async () => {
        calls++;
        return new Response(null, { status: 429, headers: { "retry-after": "120" } });
      },
      sleepFn: async () => { throw new Error("Must not retry before Retry-After"); },
    }),
    (error) => isRateLimitError(error) && error.rateLimitedAttempts === 1,
  );
  assert.equal(calls, 1);
});

test("HTTP 500 remains a real response failure and is not retried", async () => {
  let calls = 0;
  const result = await fetchWithRateLimitRetry("https://otellotracker.com/api/test", {
    fetchFn: async () => {
      calls++;
      return new Response(null, { status: 500 });
    },
  });
  assert.equal(result.response.status, 500);
  assert.equal(result.rateLimitedAttempts, 0);
  assert.equal(calls, 1);
});

test("A single synthetic API timeout is retried and reported without failure", async () => {
  let calls = 0;
  const waits = [];
  const result = await retryOnTimeout(async () => {
    calls++;
    if (calls === 1) throw new DOMException("The operation was aborted due to timeout", "TimeoutError");
    return { status: 200, totalMs: 45 };
  }, { sleepFn: async (ms) => { waits.push(ms); } });
  assert.equal(calls, 2);
  assert.deepEqual(waits, [2000]);
  assert.equal(result.timeoutRetries, 1);
  assert.deepEqual(result.value, { status: 200, totalMs: 45 });
});

test("Repeated API timeouts exhaust the retry budget and remain failures", async () => {
  let calls = 0;
  const waits = [];
  await assert.rejects(
    () => retryOnTimeout(async () => {
      calls++;
      throw new DOMException("The operation was aborted due to timeout", "TimeoutError");
    }, { sleepFn: async (ms) => { waits.push(ms); } }),
    (error) => isTimeoutError(error) && error.timeoutAttempts === 2,
  );
  assert.equal(calls, 2);
  assert.deepEqual(waits, [2000]);
});

test("Non-timeout network errors, HTTP errors and unrelated aborts are never retried", async () => {
  for (const error of [
    new Error("HTTP 500"),
    new TypeError("fetch failed: DNS lookup failed"),
    new DOMException("Manual cancellation", "AbortError"),
  ]) {
    let calls = 0;
    await assert.rejects(() => retryOnTimeout(async () => {
      calls++;
      throw error;
    }, { sleepFn: async () => { throw new Error("unexpected retry"); } }), (raised) => raised === error);
    assert.equal(calls, 1);
  }
  assert.equal(isTimeoutError(new DOMException("Canceled", "AbortError")), false);
});

test("Health Server-Timing exposes only the D1 duration", () => {
  assert.equal(parseHealthD1Timing("d1;dur=12.35"), 12.4);
  assert.equal(parseHealthD1Timing('other;dur=3, d1;dur=0.42;desc="read"'), 0.4);
  assert.equal(parseHealthD1Timing("other;dur=3"), null);
  assert.equal(parseHealthD1Timing("d1;dur=invalid"), null);
  assert.equal(parseHealthD1Timing(null), null);
});
